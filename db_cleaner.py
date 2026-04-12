from __future__ import annotations

import csv
import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


DB_PATH = Path(__file__).with_name("db.sqlite")
FOOD_SUBSTANCES_PATH = Path(__file__).with_name("FoodSubstances.csv")
FOOD_SUBSTANCES_HEADER = "CAS Reg No (or other ID),Substance,Other Names,Used for (Technical Effect)"


def clean_raw_material_sku(sku: str) -> str:
    parts = [part.strip() for part in str(sku or "").split("-") if part.strip()]
    if len(parts) >= 4 and parts[0].upper() == "RM":
        return " ".join(parts[2:-1]).strip()
    return normalize_display_text(str(sku or "").replace("-", " "))


def normalize_display_text(value: str) -> str:
    text = str(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def tokenize_compare_text(value: str) -> list[str]:
    normalized = normalize_display_text(value).lower()
    normalized = re.sub(r"\b([a-z])[\s_-]+(\d+)\b", r"\1\2", normalized)
    return sorted(dict.fromkeys(re.findall(r"[a-z0-9]+", normalized)))


def build_compare_key(value: str) -> str:
    return "|".join(tokenize_compare_text(value))


def join_unique_values(series: pd.Series, limit: int = 5) -> str:
    values = [normalize_display_text(value) for value in series.fillna("").tolist()]
    values = [value for value in values if value]
    unique_values = list(dict.fromkeys(values))
    if not unique_values:
        return ""
    return " | ".join(unique_values[:limit])


def join_unique_list_values(series: pd.Series, limit: int = 8) -> str:
    values: list[str] = []
    for item in series.tolist():
        if isinstance(item, list):
            values.extend(normalize_display_text(value) for value in item if normalize_display_text(value))
        else:
            value = normalize_display_text(item)
            if value:
                values.append(value)
    unique_values = list(dict.fromkeys(values))
    if not unique_values:
        return ""
    return " | ".join(unique_values[:limit])


def extract_other_name_heads(value: str) -> list[str]:
    text = str(value or "")
    parts = re.split(r"<br\s*/?>", text, flags=re.IGNORECASE)
    heads: list[str] = []
    for part in parts:
        cleaned = re.sub(r"&diams;|<[^>]+>", " ", part, flags=re.IGNORECASE)
        cleaned = normalize_display_text(cleaned)
        if not cleaned:
            continue
        head = normalize_display_text(cleaned.split(",", 1)[0])
        if head:
            heads.append(head)
    return list(dict.fromkeys(heads))


def extract_unique_pipe_values(series: pd.Series) -> list[str]:
    values: list[str] = []
    for item in series.fillna("").tolist():
        for part in str(item).split("|"):
            cleaned = normalize_display_text(part)
            if cleaned:
                values.append(cleaned)
    return list(dict.fromkeys(values))


@st.cache_data(show_spinner=False)
def load_raw_materials(db_path: str) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        query = """
            SELECT
                p.Id AS product_id,
                p.SKU AS original_sku,
                p.CompanyId AS company_id,
                c.Name AS company_name
            FROM Product p
            LEFT JOIN Company c ON c.Id = p.CompanyId
            WHERE p.Type = 'raw-material'
            ORDER BY p.Id
        """
        raw_df = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    raw_df["clean_sku"] = raw_df["original_sku"].map(clean_raw_material_sku)
    raw_df["material_groups"] = raw_df["clean_sku"].map(build_compare_key)
    raw_df["sku_key"] = raw_df["material_groups"]
    raw_df["company_name"] = raw_df["company_name"].fillna("").map(normalize_display_text)
    return raw_df


@st.cache_data(show_spinner=False)
def load_supplier_product_links(db_path: str) -> pd.DataFrame:
    connection = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        query = """
            SELECT
                sp.ProductId AS product_id,
                sp.SupplierId AS supplier_id,
                s.Name AS supplier_name
            FROM Supplier_Product sp
            LEFT JOIN Supplier s ON s.Id = sp.SupplierId
            ORDER BY sp.ProductId, sp.SupplierId
        """
        supplier_df = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    supplier_df["supplier_name"] = supplier_df["supplier_name"].fillna("").map(normalize_display_text)
    return supplier_df


@st.cache_data(show_spinner=False)
def load_food_substances(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    lines = path.read_text(encoding="latin-1").splitlines()
    header_index = next(
        index for index, line in enumerate(lines) if line.startswith(FOOD_SUBSTANCES_HEADER)
    )

    reader = csv.DictReader(lines[header_index:])
    substances_df = pd.DataFrame(reader)
    substances_df["Substance"] = substances_df["Substance"].fillna("").map(normalize_display_text)
    substances_df["Other Names"] = substances_df["Other Names"].fillna("").map(normalize_display_text)
    substances_df["Used for (Technical Effect)"] = (
        substances_df["Used for (Technical Effect)"].fillna("").map(normalize_display_text)
    )
    substances_df["substance_key"] = substances_df["Substance"].map(build_compare_key)
    substances_df["substance_groups"] = substances_df["substance_key"]
    substances_df["other_name_heads"] = substances_df["Other Names"].map(extract_other_name_heads)
    substances_df["other_name_head_text"] = substances_df["other_name_heads"].map(
        lambda values: " | ".join(values)
    )
    substances_df = substances_df[substances_df["Substance"] != ""].copy()
    return substances_df


def build_overview(raw_materials_df: pd.DataFrame, substances_df: pd.DataFrame) -> pd.DataFrame:
    prepared_substances_df = substances_df.dropna(subset=["substance_key"]).copy()
    prepared_substances_df["substance_token_set"] = prepared_substances_df["substance_groups"].map(
        lambda value: set(value.split("|")) if value else set()
    )

    match_rows: list[dict[str, object]] = []
    for material_groups in raw_materials_df["material_groups"].dropna().drop_duplicates().tolist():
        material_token_set = set(str(material_groups).split("|")) if material_groups else set()
        matched_df = prepared_substances_df[
            prepared_substances_df["substance_token_set"].map(
                lambda token_set: bool(token_set) and token_set.issubset(material_token_set)
            )
        ].copy()

        if matched_df.empty:
            continue

        has_exact_match = (matched_df["substance_groups"] == material_groups).any()
        match_rows.append(
            {
                "material_groups": material_groups,
                "matched_substances": join_unique_values(matched_df["Substance"]),
                "matched_other_names": join_unique_list_values(matched_df["other_name_heads"]),
                "technical_effects": join_unique_values(matched_df["Used for (Technical Effect)"]),
                "match_count": int(len(matched_df)),
                "match_mode": "exact" if has_exact_match else "subset",
                "matched_substance_keys": matched_df["substance_groups"].tolist(),
                "matched_substance_groups": join_unique_values(matched_df["substance_groups"], limit=12),
            }
        )

    matches_df = pd.DataFrame(match_rows)
    overview_df = raw_materials_df.merge(matches_df, how="left", on="material_groups")
    overview_df["match_count"] = overview_df["match_count"].fillna(0).astype(int)
    overview_df["is_match"] = overview_df["match_count"] > 0
    overview_df["matched_substances"] = overview_df["matched_substances"].fillna("")
    overview_df["matched_other_names"] = overview_df["matched_other_names"].fillna("")
    overview_df["technical_effects"] = overview_df["technical_effects"].fillna("")
    overview_df["match_mode"] = overview_df["match_mode"].fillna("none")
    overview_df["matched_substance_groups"] = overview_df["matched_substance_groups"].fillna("")
    overview_df["matched_substance_keys"] = overview_df["matched_substance_keys"].map(
        lambda value: value if isinstance(value, list) else []
    )
    overview_df = overview_df.sort_values(["clean_sku", "product_id"], ignore_index=True)
    return overview_df


def build_supplier_status(raw_materials_df: pd.DataFrame, supplier_links_df: pd.DataFrame) -> pd.DataFrame:
    if supplier_links_df.empty:
        supplier_summary_df = pd.DataFrame(
            {
                "product_id": raw_materials_df["product_id"].tolist(),
                "supplier_count": 0,
                "supplier_names": "",
            }
        )
    else:
        supplier_summary_df = (
            supplier_links_df.groupby("product_id", as_index=False)
            .agg(
                supplier_count=("supplier_id", "nunique"),
                supplier_names=("supplier_name", join_unique_values),
            )
        )

    supplier_status_df = raw_materials_df[["product_id", "clean_sku", "company_name"]].merge(
        supplier_summary_df, how="left", on="product_id"
    )
    supplier_status_df["supplier_count"] = supplier_status_df["supplier_count"].fillna(0).astype(int)
    supplier_status_df["supplier_names"] = supplier_status_df["supplier_names"].fillna("")
    supplier_status_df["supplier_status"] = supplier_status_df["supplier_count"].map(
        lambda count: "nicht gewechselt" if count == 1 else ("gewechselt" if count > 1 else "kein supplier")
    )
    return supplier_status_df.sort_values(["product_id"], ignore_index=True)


def apply_filters(overview_df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("Filter")
    text_filter = st.sidebar.text_input("Suche SKU oder Substance", value="").strip().lower()
    match_filter = st.sidebar.selectbox(
        "Match-Status",
        options=["alle", "nur matches", "nur ohne match"],
        index=0,
    )

    filtered_df = overview_df.copy()
    if text_filter:
        mask = (
            filtered_df["clean_sku"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["original_sku"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["material_groups"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["company_name"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["matched_substances"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["matched_other_names"].str.lower().str.contains(text_filter, na=False)
            | filtered_df["technical_effects"].str.lower().str.contains(text_filter, na=False)
        )
        filtered_df = filtered_df[mask].copy()

    if match_filter == "nur matches":
        filtered_df = filtered_df[filtered_df["is_match"]].copy()
    elif match_filter == "nur ohne match":
        filtered_df = filtered_df[~filtered_df["is_match"]].copy()

    return filtered_df.reset_index(drop=True)


def render_app() -> None:
    st.set_page_config(page_title="SKU vs FoodSubstances", layout="wide")
    st.title("SKU zu FoodSubstances")
    st.caption(
        "Read-only Uebersicht: `db.sqlite` wird nicht veraendert. "
        "Die SKU wird nur fuer den Vergleich bereinigt."
    )

    raw_materials_df = load_raw_materials(str(DB_PATH))
    supplier_links_df = load_supplier_product_links(str(DB_PATH))
    substances_df = load_food_substances(str(FOOD_SUBSTANCES_PATH))
    overview_df = build_overview(raw_materials_df, substances_df)
    supplier_status_df = build_supplier_status(raw_materials_df, supplier_links_df)
    filtered_df = apply_filters(overview_df)
    filtered_supplier_status_df = supplier_status_df[
        supplier_status_df["product_id"].isin(filtered_df["product_id"])
    ].copy()

    total_rows = len(overview_df)
    total_unique = overview_df["clean_sku"].nunique()
    total_matches = int(overview_df["is_match"].sum())
    total_unmatched = int((~overview_df["is_match"]).sum())

    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Raw-material rows", total_rows)
    metric_2.metric("Unique clean SKU", total_unique)
    metric_3.metric("Mit Substance-Match", total_matches)
    metric_4.metric("Ohne Match", total_unmatched)

    st.subheader("Overview")
    display_df = filtered_df[
        [
            "product_id",
            "company_name",
            "clean_sku",
            "original_sku",
            "material_groups",
            "match_mode",
            "matched_substances",
            "matched_substance_groups",
            "matched_other_names",
            "technical_effects",
            "sku_key",
        ]
    ].rename(
        columns={
            "product_id": "product_id",
            "company_name": "company_name",
            "clean_sku": "clean_sku",
            "original_sku": "original_sku",
            "material_groups": "material_groups",
            "match_mode": "match_mode",
            "matched_substances": "matched_substances",
            "matched_substance_groups": "matched_substance_groups",
            "matched_other_names": "matched_other_names",
            "technical_effects": "technical_effects",
            "sku_key": "compare_key",
        }
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("Unique Matched Substances")
    unique_matched_substances = extract_unique_pipe_values(filtered_df["matched_substances"])
    unique_matched_df = pd.DataFrame({"matched_substance": unique_matched_substances})
    st.caption(f"Eindeutige matched_substances aus der aktuellen Overview: {len(unique_matched_df)}")
    if unique_matched_df.empty:
        st.info("Keine matched_substances im aktuellen Filter gefunden.")
    else:
        st.dataframe(unique_matched_df, use_container_width=True, hide_index=True)

    st.subheader("Supplier Product Status")
    supplier_display_df = filtered_supplier_status_df[
        ["product_id", "company_name", "clean_sku", "supplier_count", "supplier_status", "supplier_names"]
    ]
    st.caption(
        "Abgleich: `Supplier_Product.ProductId` gegen `raw_material_attributes.product_id`."
    )
    if supplier_display_df.empty:
        st.info("Keine Supplier-Produkt-Zeilen fuer den aktuellen Filter gefunden.")
    else:
        st.dataframe(supplier_display_df, use_container_width=True, hide_index=True)

    st.subheader("Detail Rows")
    if filtered_df.empty:
        st.info("Keine Zeilen fuer den aktuellen Filter gefunden.")
        return

    detail_options = (
        filtered_df.assign(
            detail_label=filtered_df.apply(
                lambda row: f"{row['product_id']} | {row['company_name']} | {row['clean_sku']}",
                axis=1,
            )
        )[["product_id", "detail_label"]]
    )
    selected_label = st.selectbox("Produktzeile", options=detail_options["detail_label"].tolist(), index=0)

    if selected_label:
        selected_product_id = int(
            detail_options.loc[detail_options["detail_label"] == selected_label, "product_id"].iloc[0]
        )
        selected_products_df = raw_materials_df[raw_materials_df["product_id"] == selected_product_id].copy()
        matched_substance_keys = (
            filtered_df.loc[filtered_df["product_id"] == selected_product_id, "matched_substance_keys"].iloc[0]
        )
        selected_substances_df = substances_df[
            substances_df["substance_groups"].isin(matched_substance_keys)
        ].copy()

        left_col, right_col = st.columns(2)

        with left_col:
            st.markdown("**Produkte aus db.sqlite**")
            st.dataframe(
                selected_products_df[
                    ["product_id", "company_name", "original_sku", "clean_sku", "material_groups", "sku_key"]
                ].rename(columns={"sku_key": "compare_key"}),
                use_container_width=True,
                hide_index=True,
            )

        with right_col:
            st.markdown("**Treffer in FoodSubstances.csv**")
            if selected_substances_df.empty:
                st.info("Kein Substance-Match fuer diese SKU gefunden.")
            else:
                st.dataframe(
                    selected_substances_df[
                        [
                            "Substance",
                            "substance_groups",
                            "other_name_head_text",
                            "Other Names",
                            "Used for (Technical Effect)",
                            "substance_key",
                        ]
                    ].rename(
                        columns={
                            "other_name_head_text": "other_name_heads",
                            "substance_key": "compare_key",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )


def is_running_in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


if is_running_in_streamlit():
    render_app()
elif __name__ == "__main__":
    print("Use: streamlit run db_cleaner.py")
