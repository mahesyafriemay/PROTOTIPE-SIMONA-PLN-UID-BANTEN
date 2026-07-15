import streamlit as st
import pandas as pd
from data import (
    init_demo_data, get_units, get_periods, get_indicators, get_aspects,
    get_assessments_for_units, get_unit_by_id, approve_assessment, request_revision,
    get_reviews_for, get_assessment, update_assessment_by_uid,
)
from ui import inject_global_style, render_topbar, render_sidebar_profile

init_demo_data()
inject_global_style()
render_topbar()
render_sidebar_profile()

if not st.session_state.get("is_authenticated"):
    st.warning("Silakan masuk terlebih dahulu di halaman utama.")
    st.stop()

if st.session_state["role"] != "UID":
    st.error("Halaman ini khusus untuk role UID.")
    st.stop()

fullname = st.session_state["fullname"]

st.title("Review & Edit Assessment")
st.caption(
    "UID dapat memeriksa, mengubah level atau catatan assessment yang sudah disubmit, "
    "kemudian menyetujui atau mengembalikannya untuk revisi."
)

periods_df = get_periods().copy()
periods_df["label"] = periods_df.apply(lambda r: f"{r['month']:02d}/{r['year']} ({r['status']})", axis=1)
selected_label = st.selectbox("Periode", periods_df["label"].tolist())
period_row = periods_df[periods_df["label"] == selected_label].iloc[0]
period_id = period_row["id"]
is_period_locked = period_row["status"] == "LOCKED"

if is_period_locked:
    st.warning("Periode ini sudah LOCKED. Data hanya dapat dilihat dan tidak dapat diedit.")

all_units = get_units()
unit_ids = all_units[all_units["type"] != "UID"]["id"].tolist()
all_assessments = get_assessments_for_units(unit_ids, period_id)

# Data yang sudah pernah dikirim ke UID, termasuk yang sudah disetujui.
reviewable = [a for a in all_assessments if a.get("status") in ("SUBMITTED", "IN_REVIEW", "APPROVED")]

if not reviewable:
    st.info("Belum ada assessment yang sudah disubmit untuk periode ini.")
    st.stop()

indicators_all = get_indicators()
ind_lookup = {i["id"]: i for i in indicators_all}
aspects_lookup = {a["id"]: a["name"] for _, a in get_aspects().iterrows()}

rows = []
for a in reviewable:
    ind = ind_lookup.get(a["indicator_id"], {})
    unit = get_unit_by_id(a["unit_id"])
    rows.append({
        "unit_id": a["unit_id"],
        "indicator_id": a["indicator_id"],
        "unit_name": unit["name"] if unit else "-",
        "unit_type": unit["type"] if unit else "UP3",
        "aspect_name": aspects_lookup.get(ind.get("aspect_id"), "-"),
        "indicator_name": ind.get("name", "-"),
        "level": a.get("level"),
        "score": a.get("score"),
        "status": a.get("status"),
        "notes": a.get("notes", ""),
    })
review_df = pd.DataFrame(rows)

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    unit_filter = st.selectbox("Filter Unit", ["Semua"] + sorted(review_df["unit_name"].unique().tolist()))
with filter_col2:
    status_filter = st.selectbox(
        "Filter Status",
        ["Semua Tersubmit", "Menunggu Review", "Disetujui"],
    )

filtered_df = review_df.copy()
if unit_filter != "Semua":
    filtered_df = filtered_df[filtered_df["unit_name"] == unit_filter]
if status_filter == "Menunggu Review":
    filtered_df = filtered_df[filtered_df["status"].isin(["SUBMITTED", "IN_REVIEW"])]
elif status_filter == "Disetujui":
    filtered_df = filtered_df[filtered_df["status"] == "APPROVED"]

if filtered_df.empty:
    st.info("Tidak ada data yang sesuai dengan filter.")
    st.stop()

st.dataframe(
    filtered_df[["unit_name", "aspect_name", "indicator_name", "level", "score", "status"]].rename(columns={
        "unit_name": "Unit",
        "aspect_name": "Aspek",
        "indicator_name": "Indikator",
        "level": "Level",
        "score": "Kontribusi Nilai",
        "status": "Status",
    }),
    use_container_width=True,
    hide_index=True,
)

st.divider()
st.markdown("### Detail, Edit Data & Keputusan")

filtered_df = filtered_df.copy()
filtered_df["display_label"] = filtered_df.apply(
    lambda r: f"{r['unit_name']} · {r['aspect_name']} · {r['indicator_name']} · {r['status']}", axis=1
)
selected = st.selectbox("Pilih assessment", filtered_df["display_label"].tolist())
row = filtered_df[filtered_df["display_label"] == selected].iloc[0]

assessment_detail = get_assessment(row["unit_id"], period_id, row["indicator_id"]) or {}
ind_detail = ind_lookup.get(row["indicator_id"], {})
max_level = max((lv["level"] for lv in ind_detail.get("levels", [])), default=(5 if row["unit_type"] == "UP3" else 3))
current_level = int(row["level"]) if pd.notna(row["level"]) else 1
current_notes = row.get("notes") if pd.notna(row.get("notes")) else ""

col_detail, col_action = st.columns([1.8, 1.2])

with col_detail:
    st.write(f"**Unit:** {row['unit_name']} ({row['unit_type']})")
    st.write(f"**Aspek:** {row['aspect_name']}")
    st.write(f"**Indikator:** {row['indicator_name']}")
    st.write(f"**Status saat ini:** `{row['status']}`")
    st.write(f"**Level saat ini:** {current_level} — **Kontribusi Nilai:** {row['score']}")

    level_desc = next(
        (lv["level_label"] for lv in ind_detail.get("levels", []) if lv["level"] == current_level),
        "-",
    )
    st.caption(f"Kriteria Level {current_level}: {level_desc}")
    st.write(f"**Catatan assessment:** {current_notes or '-'}")

    st.markdown("**Evidence:**")
    evidences = assessment_detail.get("evidences", [])
    if evidences:
        for idx, ev in enumerate(evidences):
            file_bytes = ev.get("file_bytes")
            mime_type = ev.get("mime_type") or ""
            ev_col1, ev_col2 = st.columns([4, 1])
            ev_col1.write(ev["filename"])
            if file_bytes:
                ev_col2.download_button(
                    "Download",
                    data=file_bytes,
                    file_name=ev["filename"],
                    mime=mime_type or "application/octet-stream",
                    key=f"review_dl_{idx}_{row['unit_id']}_{row['indicator_id']}",
                )
                if mime_type.startswith("image/"):
                    st.image(file_bytes, caption=ev["filename"], width=400)
                elif mime_type == "application/pdf":
                    import base64
                    b64 = base64.b64encode(file_bytes).decode()
                    st.markdown(
                        f'<iframe src="data:application/pdf;base64,{b64}" '
                        f'width="100%" height="500" style="border:1px solid #E4E9F2;border-radius:8px;">'
                        f'</iframe>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Konten file tidak tersimpan.")
    else:
        st.caption("Tidak ada evidence yang diupload.")

    st.markdown("**Riwayat Review dan Perubahan UID:**")
    reviews = get_reviews_for(row["unit_id"], period_id, row["indicator_id"])
    if reviews:
        for rv in sorted(reviews, key=lambda x: x["time"], reverse=True):
            st.write(f"- `{rv['decision']}` oleh **{rv['reviewer']}**: {rv.get('comments') or '-'}")
    else:
        st.caption("Belum ada riwayat review.")

with col_action:
    st.markdown("#### Edit Data Assessment")
    edited_level = st.select_slider(
        "Level hasil koreksi UID",
        options=list(range(1, max_level + 1)),
        value=current_level,
        disabled=is_period_locked,
        key=f"uid_level_{row['unit_id']}_{period_id}_{row['indicator_id']}",
    )
    edited_level_desc = next(
        (lv["level_label"] for lv in ind_detail.get("levels", []) if lv["level"] == edited_level),
        "-",
    )
    st.caption(f"Kriteria Level {edited_level}: {edited_level_desc}")

    edited_notes = st.text_area(
        "Catatan assessment hasil koreksi UID",
        value=current_notes,
        height=120,
        disabled=is_period_locked,
        key=f"uid_notes_{row['unit_id']}_{period_id}_{row['indicator_id']}",
    )
    edit_reason = st.text_area(
        "Alasan perubahan (opsional)",
        height=80,
        disabled=is_period_locked,
        key=f"uid_edit_reason_{row['unit_id']}_{period_id}_{row['indicator_id']}",
    )

    if st.button(
        "Simpan Perubahan UID",
        type="primary",
        use_container_width=True,
        disabled=is_period_locked,
    ):
        updated = update_assessment_by_uid(
            row["unit_id"],
            period_id,
            row["indicator_id"],
            edited_level,
            edited_notes,
            fullname,
            edit_reason,
        )
        if updated:
            st.success("Data assessment berhasil diperbarui oleh UID.")
            st.rerun()
        else:
            st.error("Data tidak dapat diperbarui karena status assessment tidak sesuai.")

    st.divider()
    st.markdown("#### Keputusan Review")
    comments = st.text_area(
        "Komentar keputusan",
        key=f"review_comments_{row['unit_id']}_{period_id}_{row['indicator_id']}",
        height=100,
        disabled=is_period_locked,
    )

    if st.button(
        "Approve",
        type="primary",
        use_container_width=True,
        disabled=is_period_locked,
        key=f"approve_{row['unit_id']}_{period_id}_{row['indicator_id']}",
    ):
        approve_assessment(row["unit_id"], period_id, row["indicator_id"], fullname, comments)
        st.success("Assessment di-approve.")
        st.rerun()

    if st.button(
        "Kembalikan untuk Revisi",
        use_container_width=True,
        disabled=is_period_locked,
        key=f"revision_{row['unit_id']}_{period_id}_{row['indicator_id']}",
    ):
        if not comments.strip():
            st.error("Komentar wajib diisi ketika meminta revisi.")
        else:
            request_revision(row["unit_id"], period_id, row["indicator_id"], fullname, comments)
            st.warning("Assessment dikembalikan untuk revisi.")
            st.rerun()
