"""Chạy pipeline xử lý data cho mọi shop của một split.

    cd "code solve data"
    python -m datamate.run_all ../train/train/data
    python -m datamate.run_all ../public_test/public_test/data --out "../solve data"

Hiện có: bước 1 (đọc file, cắt bảng) + bước 2 (parse giá trị) + bước 3 (README, map tên cột).
Data gốc chỉ được đọc. Kết quả ghi vào <out>/<split>/<shop>/:
    tables/<bảng>.csv   bảng đã parse; cột parse từ chuỗi có thêm cột "<tên>__raw" giữ nguyên gốc
    _columns.csv        mỗi cột một dòng: kiểu suy ra, số ô, số ô không parse được, ví dụ lỗi
    _dropped.csv        các dòng bị bỏ ở bước 1 (dòng tổng, header lặp) kèm sheet + số dòng
    samples/<bảng>.csv  300 dòng đầu của bảng đã parse (luôn ghi, kể cả khi --skip-tables)
    _mapping.csv        cột gốc -> tên chuẩn, nguồn bằng chứng, mô tả README, ghi chú
    _readme.txt         README đã parse: ngày cuối dữ liệu, quy đổi đơn vị, quy ước
và <out>/<split>/report.csv: tóm tắt mỗi shop một dòng.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

import pandas as pd

from datamate.loader import labels, repair
from datamate.loader.build import Built, build_shop, rename_columns
from datamate.loader.repair import repair_column
from datamate.loader.conventions import read_conventions
from datamate.loader.header import Table, load_tables
from datamate.loader.mapping import TableInput, build_name_dict, map_shop, with_base
from datamate.loader.parsers import fold, norm_status, parse_column, parse_number, year_from_text
from datamate.loader.read_files import read_shop
from datamate.loader.readme import ReadmeInfo, parse_readme
from datamate.loader.shopmeta import load_calendar, parse_rulebook, split_root

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "solve data")


def split_name(split_dir: str) -> str:
    """'../train/train/data' -> 'train'."""
    parts = [p for p in os.path.normpath(os.path.abspath(split_dir)).split(os.sep) if p]
    return parts[-2] if parts[-1].lower() == "data" and len(parts) >= 2 else parts[-1]


SAMPLE_ROWS = 300


def parse_table(t: Table) -> tuple[pd.DataFrame, list[dict], TableInput]:
    """Parse mọi cột của bảng. Trả (DataFrame, profile từng cột, đầu vào cho mapping)."""
    years = [year_from_text(sheet, t.file) for sheet, _ in t.src]
    data, profile, raw_s, parsed_s = {}, [], {}, {}
    for j, col in enumerate(t.columns):
        raw = [r[j] for r in t.rows]
        # ô số / ngày luật không đọc được: LLM viết lại, bộ đọc của luật đọc lại (bật cùng --llm)
        res = repair_column(col, raw, years, parse_column(col, raw, years))
        raw_s[col], parsed_s[col] = raw[:SAMPLE_ROWS], res["values"][:SAMPLE_ROWS]
        data[col] = res["values"]
        keep_raw = res["kind"] in ("number", "datetime", "bool") and res["had_text"]
        if keep_raw:
            data[f"{col}__raw"] = [None if v is None else str(v) for v in raw]
        num_rate = None
        if res["kind"] == "text" and res["n"]:
            num_rate = round(sum(parse_number(v) is not None for v in raw if v is not None) / res["n"], 3)
        profile.append({
            "table": t.name, "column": col, "kind": res["kind"], "group": t.groups.get(col),
            "n": res["n"], "null": len(raw) - res["n"], "n_fail": res["n_fail"],
            "fail_examples": " | ".join(res["fail_examples"]),
            "units": " ".join(f"{u}:{c}" for u, c in sorted(res["units"].items(), key=lambda x: -x[1])[:6]),
            "month_first": res["month_first"] or None, "num_rate_if_text": num_rate,
            "repaired": res.get("repaired"),
            "has_raw": keep_raw,
            "samples": " | ".join(list(dict.fromkeys(str(v) for v in raw if v is not None))[:4]),
        })
    df = pd.DataFrame(data)
    df.insert(0, "_src_row", [r for _, r in t.src])
    df.insert(0, "_src_sheet", [s for s, _ in t.src])
    df.insert(0, "_src_file", t.file)
    tin = TableInput(t.name, t.file, t.sheets, t.columns, {p["column"]: p["kind"] for p in profile}, raw_s, parsed_s)
    return df, profile, tin


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name)


def _readme_text(info: ReadmeInfo) -> str:
    lines = [f"shop: {info.shop}", f"dữ liệu đến hết: {info.data_end}",
             f"file: {info.files}", f"bảng sqlite: {info.sqlite_tables}",
             f"file quy đổi: {info.conversion_files}", "", "== mô tả", info.intro, "", "== quy ước"]
    lines += [f"- [{topic}] {body}" for topic, body in info.conventions]
    lines += ["", f"== quy đổi đơn vị ghi trong README ({len(info.unit_conversions)})"]
    lines += [f"- {c.product}: 1 {c.big_unit} = {c.factor:g} {c.base_unit}" for c in info.unit_conversions]
    return "\n".join(lines)


def run_shop(shop_dir: str, out_dir: str, readme: ReadmeInfo, name_dict: dict[str, str],
             write_tables: bool = True, build: bool = True, shared: dict | None = None,
             use_llm: bool = False, sua: dict | None = None) -> dict:
    t0 = time.time()
    sua = sua or {}
    tables, warnings = load_tables(read_shop(shop_dir))
    bo = {fold(str(x)).strip() for x in sua.get("bo_dong") or [] if str(x).strip()}
    if bo:      # vòng tự sửa: bỏ dòng có ô chữ đúng nhãn (dòng tổng / dòng ghi chú lọt bước cắt bảng)
        for t in tables:
            keep = [i for i, r in enumerate(t.rows)
                    if not any(isinstance(c, str) and fold(c).strip() in bo for c in r)]
            if len(keep) < len(t.rows):
                t.dropped += [(t.src[i][0], t.src[i][1], "tự sửa: dòng nhãn bỏ", str(t.rows[i])[:80])
                              for i in range(len(t.rows)) if i not in set(keep)]
                t.rows, t.src = [t.rows[i] for i in keep], [t.src[i] for i in keep]
    for sub in ("tables", "samples"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    profiles, dropped, inputs, dfs = [], [], [], []
    for t in tables:
        df, prof, tin = parse_table(t)
        if write_tables:
            df.to_csv(os.path.join(out_dir, "tables", _safe(t.name) + ".csv"), index=False, encoding="utf-8-sig")
        df.head(SAMPLE_ROWS).to_csv(os.path.join(out_dir, "samples", _safe(t.name) + ".csv"),
                                    index=False, encoding="utf-8-sig")
        inputs.append(tin)
        dfs.append(df if build else None)
        profiles.extend(prof)
        dropped.extend({"table": t.name, "file": t.file, "sheet": s, "row": r, "reason": why, "text": txt}
                       for s, r, why, txt in t.dropped)

    mappings, items = [], []
    over = {fold(k): {c: v for c, v in d.items()} for k, d in (sua.get("cot") or {}).items()}
    for tin, maps, df in zip(inputs, map_shop(inputs, readme, name_dict, use_llm=use_llm).values(), dfs):
        for m in maps:          # vòng tự sửa: cột gốc -> tên chuẩn (null = bỏ tên chuẩn)
            d = over.get(fold(tin.name)) or over.get(fold(tin.name.split("__")[0])) or {}
            if m.column in d:
                m.canonical, m.source = d[m.column], "tu_sua"
                m.note = (m.note + " | " if m.note else "") + "tự sửa"
        if build:
            rdf, cols = rename_columns(df, maps, tin.kinds)
            items.append(Built("", tin.name, "", rdf, cols, [tin.name]))
        for m in maps:
            row = vars(m) | {"kind": tin.kinds.get(m.column)}
            if m.canonical == "status":
                vals = [v for v in tin.raw[m.column] if v is not None]
                cover = sum(norm_status(v) is not None for v in vals)
                row["note"] = f"{row['note']} norm_status nhận {cover}/{len(vals)} mẫu".strip()
            mappings.append(row)
    pd.DataFrame(profiles).to_csv(os.path.join(out_dir, "_columns.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(dropped, columns=["table", "file", "sheet", "row", "reason", "text"]).to_csv(
        os.path.join(out_dir, "_dropped.csv"), index=False, encoding="utf-8-sig")
    pd.DataFrame(mappings).to_csv(os.path.join(out_dir, "_mapping.csv"), index=False, encoding="utf-8-sig")
    with open(os.path.join(out_dir, "_readme.txt"), "w", encoding="utf-8") as f:
        f.write(_readme_text(readme))
    kinds = pd.Series([p["kind"] for p in profiles]).value_counts().to_dict()
    nonempty = [m for m in mappings if m["kind"] != "empty"]
    shop = os.path.basename(os.path.normpath(shop_dir))
    bres = {}
    # quy ước trong README (tiền theo nghìn, trạng thái ghi ở cột khác...): LLM đọc, build kiểm rồi áp dụng
    conventions = read_conventions(readme, {t.name: list(t.columns) for t in tables}) if use_llm else {}
    if build:
        from datamate.loader import build as _b, parsers as _p
        _p.EXTRA_STATUS = {fold(str(k)).strip(): v for k, v in (sua.get("trang_thai") or {}).items()}
        _b.ROLE_OVERRIDE = {fold(k): v for k, v in (sua.get("vai_tro") or {}).items()}
        try:
            bres = build_shop(shop, items, readme, dropped, os.path.join(out_dir, f"{shop}.duckdb"), shared,
                              conventions)
        finally:
            _p.EXTRA_STATUS, _b.ROLE_OVERRIDE = {}, {}
        pd.DataFrame([{"table_name": n, **{k: (v if not isinstance(v, (dict, list)) else str(v))
                                           for k, v in s.items()}} for n, s in bres["tables"].items()]
                     ).to_csv(os.path.join(out_dir, "_build.csv"), index=False, encoding="utf-8-sig")
    return {
        "shop": os.path.basename(shop_dir), "tables": len(tables), "rows": sum(len(t.rows) for t in tables),
        "dropped_rows": len(dropped), "columns": len(profiles),
        **{f"cols_{k}": kinds.get(k, 0) for k in ("number", "datetime", "bool", "text", "empty")},
        "fail_cells": sum(p["n_fail"] for p in profiles),
        "cols_with_fail": sum(p["n_fail"] > 0 for p in profiles),
        "data_end": readme.data_end, "readme_col_docs": sum(d.source == "columns" for d in readme.columns),
        "mapped": sum(m["canonical"] is not None for m in nonempty), "mappable_cols": len(nonempty),
        "tables_out": bres.get("tables_out"), "conversions": bres.get("conversions"),
        "abbreviations": bres.get("abbreviations"), "aliases": bres.get("aliases"),
        "conversions_id_filled": bres.get("conversions_id_filled"),
        "orders_returned_elsewhere": bres.get("orders_returned_elsewhere"),
        "orders_status_reconciled": bres.get("orders_status_reconciled"),
        "return_sources": " ".join(bres.get("return_sources") or []),
        "conventions": json.dumps(conventions, ensure_ascii=False) if conventions else None,
        "money_scale": bres.get("money_scale"), "money_scale_warning": bres.get("money_scale_warning"),
        "industry": bres.get("industry"), "industry_evidence": bres.get("industry_evidence"),
        "rulebook_section": bres.get("rulebook_section"),
        "dup_dropped": sum(s.get("dup_dropped", 0) for s in bres.get("tables", {}).values()),
        "warnings": " | ".join(warnings + bres.get("merge_warnings", [])), "seconds": round(time.time() - t0, 1),
    }


def _readme(path: str) -> ReadmeInfo:
    """README đọc lỗi (mã hoá lạ...) thì coi như không có README, không dừng cả bộ."""
    try:
        return parse_readme(path)
    except Exception as e:
        print(f"README lỗi {path}: {type(e).__name__}: {str(e)[:150]}", flush=True)
        return ReadmeInfo(shop=os.path.basename(os.path.dirname(path)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split_dir", help="thư mục data của split, vd ../train/train/data")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--shops", nargs="*", help="chỉ chạy các shop này")
    ap.add_argument("--extra-readmes", nargs="*", default=[],
                    help="thư mục data của split khác: README của chúng góp vào từ điển tên cột")
    ap.add_argument("--base-readmes", nargs="*", default=[],
                    help="thư mục chứa <shop>/README.md (vd README train trong docker/assets): chỉ bổ sung tên cột mà "
                         "README của split đang dựng chưa từng mô tả")
    ap.add_argument("--skip-tables", action="store_true", help="không ghi tables/*.csv (chạy nhanh)")
    ap.add_argument("--no-build", action="store_true", help="không ghi <shop>.duckdb (chỉ bước 1-3)")
    ap.add_argument("--llm", action="store_true", help="cột luật để trống hỏi LLM (cần DATAMATE_LLM_URL)")
    args = ap.parse_args()
    labels.ENABLED = args.llm           # nhãn luật không nhận ra (trạng thái, thanh toán, khách lẻ...) hỏi LLM
    repair.ENABLED = args.llm           # ô số / ngày luật không đọc được hỏi LLM

    split_out = os.path.join(args.out, split_name(args.split_dir))
    shops = sorted(s for s in os.listdir(args.split_dir) if os.path.isdir(os.path.join(args.split_dir, s)))
    if args.shops:
        shops = [s for s in shops if s in args.shops]
    readmes = {s: _readme(os.path.join(args.split_dir, s, "README.md")) for s in shops}
    extra = [parse_readme(os.path.join(d, s, "README.md"))
             for d in args.extra_readmes for s in sorted(os.listdir(d)) if os.path.isdir(os.path.join(d, s))]
    base = {s: _readme(os.path.join(d, s, "README.md"))
            for d in args.base_readmes for s in sorted(os.listdir(d)) if os.path.isfile(os.path.join(d, s, "README.md"))}
    base_all = build_name_dict(list(base.values()))
    root = split_root(args.split_dir)
    shared = {"calendar": load_calendar(root), "rulebook": parse_rulebook(root)}
    print(f"lịch: {None if shared['calendar'] is None else len(shared['calendar'])} ngày, "
          f"rulebook: {len(shared['rulebook'])} mục ({root})")
    rows = []
    for shop in shops:
        # leave-one-out: từ điển tên cột không dùng README của chính shop đang xử lý
        name_dict = build_name_dict([r for s, r in readmes.items() if s != shop] + extra)
        if base:
            name_dict = with_base(name_dict, base_all if shop not in base else
                                  build_name_dict([r for s, r in base.items() if s != shop]))
        try:
            r = run_shop(os.path.join(args.split_dir, shop), os.path.join(split_out, shop),
                         readmes[shop], name_dict, write_tables=not args.skip_tables, build=not args.no_build,
                         shared=shared, use_llm=args.llm)
        except Exception as e:      # một shop lỗi chỉ mất câu của shop đó, không dừng cả bộ
            print(f"{shop}: LỖI {type(e).__name__}: {str(e)[:200]}", flush=True)
            continue
        if args.llm and not args.no_build and os.environ.get("DATAMATE_TU_SUA"):
            # vòng tự sửa: khám DB vừa dựng, LLM đề xuất đọc lại sổ, chỉ nhận khi khám lại đỡ hơn
            from datamate.loader import tu_sua
            sd, nd = os.path.join(args.split_dir, shop), name_dict
            try:
                nhan = tu_sua.vong(lambda sua, out, sd=sd, nd=nd, shop=shop: run_shop(
                    sd, out, readmes[shop], nd, write_tables=not args.skip_tables, build=True, shared=shared,
                    use_llm=args.llm, sua=sua), os.path.join(split_out, shop), sd)
                if nhan:
                    print(f"{shop}: tự sửa {json.dumps(nhan, ensure_ascii=False)[:300]}", flush=True)
            except Exception as e:
                print(f"{shop}: tự sửa LỖI {type(e).__name__}: {str(e)[:200]}", flush=True)
        rows.append(r)
        print(f"{shop}: {r['tables']} bảng -> {r['tables_out']}, {r['rows']} dòng, ô lỗi={r['fail_cells']}, "
              f"map {r['mapped']}/{r['mappable_cols']} cột, bỏ trùng {r['dup_dropped']} ({r['seconds']}s)",
              flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(split_out, "report.csv"), index=False, encoding="utf-8-sig")
    print("->", os.path.abspath(split_out))


if __name__ == "__main__":
    main()
