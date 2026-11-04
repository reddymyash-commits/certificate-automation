from email_service import send_certificate
from hashlib import sha256
from io import BytesIO
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd
import streamlit as st

from certificates import create_certificate
from email_service import send_certificate

FIELDS = {
    "Name": ["Student Name", "Name", "Participant Name", "Full Name"],
    "Email": ["Student Email", "Email", "Email Address", "Personal Email"],
    "Event": ["Event", "Event Name"],
    "Certificate Type": ["Certificate Type", "Category", "Type"],
    "Student ID": ["Student ID", "ID", "Roll Number", "Roll No"],
    "Achievement": ["Achievement", "Award", "Result"],
    "Date": ["Date", "Event Date"],
}
REQUIRED = ["Name", "Email", "Event", "Certificate Type"]
EMAIL_PATTERN = r"[^@\s]+@[^@\s]+\.[^@\s]+"
TOKEN_PATTERN = r"\{\{\s*([^{}]+?)\s*\}\}"


def suggest_column(columns, names):
    """Return a dropdown position, reserving zero for no selection."""
    names = {name.strip().casefold() for name in names}
    for position, column in enumerate(columns, start=1):
        if str(column).strip().casefold() in names:
            return position
    return 0


def validate_students(data):
    """Return a report; flag every copy of a duplicate record."""
    errors = [[] for _ in range(len(data))]
    for field in REQUIRED:
        for position, value in enumerate(data[field]):
            if not value:
                errors[position].append(f"Missing {field}")
    for position, email in enumerate(data["Email"]):
        if email and not re.fullmatch(EMAIL_PATTERN, email):
            errors[position].append("Invalid email format")

    identity = "email:" + data["Email"].str.casefold()
    if "Student ID" in data:
        ids = data["Student ID"].str.casefold()
        identity = ("id:" + ids).where(ids.ne(""), identity)
    keys = pd.DataFrame({
        "Identity": identity,
        "Event": data["Event"].str.casefold(),
        "Type": data["Certificate Type"].str.casefold(),
    })
    for position, duplicate in enumerate(keys.duplicated(keep=False)):
        if duplicate:
            errors[position].append("Duplicate student/event/certificate type")
    report = data.copy()
    report.insert(0, "Source Row", range(2, len(data) + 2))
    report["Issues"] = ["; ".join(items) for items in errors]
    report["Status"] = ["Needs correction" if items else "Ready" for items in errors]
    return report


def safe_filename_part(value):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(value)).strip("_")[:60] or "record"


def render_email(text, student):
    """Replace supported placeholders without evaluating input as code."""
    return re.sub(TOKEN_PATTERN, lambda match: str(student.get(match.group(1), "")), text)


st.title("Certificate Automation")
st.write("Upload student details, validate them, and generate certificates.")
uploaded = st.file_uploader("Choose an Excel or CSV file", type=["xlsx", "csv"])
if uploaded is None:
    st.stop()

file_bytes = uploaded.getvalue()
file_key = sha256(file_bytes).hexdigest()
try:
    if uploaded.name.lower().endswith(".csv"):
        students = pd.read_csv(BytesIO(file_bytes), dtype=str)
    else:
        students = pd.read_excel(BytesIO(file_bytes), dtype=str)
    students = students.fillna("").reset_index(drop=True)
except Exception as error:
    st.error(f"Could not read the spreadsheet: {error}")
    st.stop()
if students.empty:
    st.warning("This spreadsheet has no student records.")
    st.stop()

st.success(f"Loaded {len(students)} student records.")
display = students.copy()
serial_heading = "S.No."
while serial_heading in display.columns:
    serial_heading = "_" + serial_heading
display.insert(0, serial_heading, range(1, len(display) + 1))
st.dataframe(display, hide_index=True)

st.subheader("Match your spreadsheet columns")
st.write("Check the suggested matches. Fields marked * are required.")
columns = list(students.columns)
options = [None] + columns
mapping = {}
for field, names in FIELDS.items():
    mapping[field] = st.selectbox(
        field + (" *" if field in REQUIRED else " (optional)"),
        options,
        index=suggest_column(columns, names),
        format_func=lambda value: "Not selected" if value is None else str(value),
        key=f"{file_key}_mapping_{field}",
    )

st.subheader("Upload certificate background")
background_file = st.file_uploader(
    "Choose your Canva certificate image", type=["png", "jpg", "jpeg"],
    key="certificate_background",
)
background_bytes = background_file.getvalue() if background_file else None
if background_bytes:
    try:
        st.image(background_bytes, caption="Certificate background", width=600)
    except Exception:
        st.error("Could not read this background image. Please upload another image.")
        st.stop()

# Results are valid only for the current file, mapping, and background.
signature = sha256(
    file_bytes + json.dumps(mapping, sort_keys=True).encode() + (background_bytes or b"")
).hexdigest()
if st.session_state.get("batch_signature") != signature:
    st.session_state["batch_signature"] = signature
    st.session_state.pop("validated_data", None)
    st.session_state.pop("validation_report", None)
    st.session_state.pop("certificate_records", None)

if st.button("Confirm column mapping", type="primary"):
    missing = [field for field in REQUIRED if mapping[field] is None]
    chosen = [column for column in mapping.values() if column is not None]
    if missing:
        st.error("Please select columns for: " + ", ".join(missing))
    elif len(chosen) != len(set(chosen)):
        st.error("Each field must use a different spreadsheet column.")
    else:
        mapped = pd.DataFrame({
            field: students[column].astype(str).str.strip()
            for field, column in mapping.items() if column is not None
        })
        report = validate_students(mapped)
        st.session_state["validation_report"] = report
        st.session_state["validated_data"] = mapped.loc[report["Status"].eq("Ready")].copy()
        st.session_state.pop("certificate_records", None)

if "validation_report" not in st.session_state:
    st.stop()
report = st.session_state["validation_report"]
valid_students = st.session_state["validated_data"]
invalid = report.loc[report["Status"].ne("Ready")]
st.subheader("Validation results")
left, right = st.columns(2)
left.metric("Ready records", len(valid_students))
right.metric("Records needing correction", len(invalid))
st.dataframe(report, hide_index=True)
st.caption("Source Row assumes headings in row 1. Email formatting does not verify an inbox exists. Duplicate checks apply only to this file.")
if not invalid.empty:
    st.warning("Correct flagged records in the original spreadsheet and upload it again.")
    st.download_button("Download error report", invalid.to_csv(index=False).encode("utf-8-sig"),
                       "validation_errors.csv", "text/csv")
if valid_students.empty:
    st.stop()

st.subheader("Generate certificates")
if not background_bytes:
    st.info("No background uploaded: certificates will use a plain white background.")
if st.button("Generate certificates"):
    records = []
    progress = st.progress(0)
    for number, (source_index, row) in enumerate(valid_students.iterrows(), start=1):
        student = row.to_dict()
        filename = (f"{number:04d}_{safe_filename_part(student['Name'])}_"
                    f"{safe_filename_part(student['Event'])}.pdf")
        try:
            pdf = create_certificate(student, background_bytes=background_bytes)
            records.append({"student": student, "filename": filename, "pdf": pdf,
                            "source_row": int(source_index) + 2, "error": ""})
        except Exception as error:
            records.append({"student": student, "filename": filename, "pdf": None,
                            "source_row": int(source_index) + 2, "error": str(error)})
        progress.progress(number / len(valid_students))
    st.session_state["certificate_records"] = records

records = st.session_state.get("certificate_records", [])
failed = [record for record in records if record["pdf"] is None]
successful = [record for record in records if record["pdf"] is not None]
if failed:
    st.error(f"{len(failed)} certificates could not be generated. Other records continued.")
    st.dataframe(pd.DataFrame([{"Source Row": r["source_row"], "Name": r["student"]["Name"],
                               "Error": r["error"]} for r in failed]), hide_index=True)
if not successful:
    st.stop()

zip_buffer = BytesIO()
with ZipFile(zip_buffer, "w", compression=ZIP_DEFLATED) as archive:
    for record in successful:
        archive.writestr(record["filename"], record["pdf"])
st.download_button(f"Download all {len(successful)} certificates (ZIP)",
                   zip_buffer.getvalue(), "certificates.zip", "application/zip")

st.subheader("Personalized email preview")
st.info("Preview only. No emails are sent from this version.")
st.caption("Available placeholders: " + ", ".join("{{" + field + "}}" for field in FIELDS))
subject_template = st.text_input(
    "Email subject",
    value="Congratulations! Your {{Event}} — {{Certificate Type}} Certificate",
    key="email_subject_custom",
)

body_template = st.text_area(
    "Email message",
    height=450,
    value=(
        "Dear {{Name}},\n\n"
        "Congratulations!\n\n"
        "We are delighted to recognize your achievement at {{Event}}.\n\n"
        "Your participation and accomplishment in this event deserve "
        "appreciation. We are pleased to share your personalized "
        "certificate, attached to this email.\n\n"
        "Your Achievement Details:\n"
        "- Name: {{Name}}\n"
        "- Student ID: {{Student ID}}\n"
        "- Event: {{Event}}\n"
        "- Certificate Type: {{Certificate Type}}\n"
        "- Achievement: {{Achievement}}\n"
        "- Date: {{Date}}\n\n"
        "Please find your certificate attached as a PDF.\n\n"
        "Thank you for being a part of this event. We wish you "
        "continued success in your future endeavours!\n\n"
        "Best regards,\n"
        "Certificate Automation Team\n"
        "Event Organizing Committee"
    ),
    key="email_body_custom",
)

unknown = sorted({token for token in re.findall(TOKEN_PATTERN, subject_template + "\n" + body_template)
                  if token not in FIELDS})
if unknown:
    st.error("Unknown placeholders: " + ", ".join(unknown))
    st.stop()
if not subject_template.strip() or not body_template.strip():
    st.warning("Enter both an email subject and message.")
    st.stop()
if "\n" in subject_template or "\r" in subject_template:
    st.error("The email subject must be a single line.")
    st.stop()
selected_index = st.selectbox(
    "Choose a recipient to preview", range(len(successful)),
    format_func=lambda index: (f"Row {successful[index]['source_row']}: "
                              f"{successful[index]['student']['Name']} "
                              f"({successful[index]['student']['Email']})"),
    key=f"recipient_{signature}",
)
record = successful[selected_index]
st.write("**To:**", record["student"]["Email"])
st.write("**Subject:**", render_email(subject_template, record["student"]))
st.text(render_email(body_template, record["student"]))
st.write("**Attachment:**", record["filename"])
st.download_button("Download this recipient's certificate to check it",
                   record["pdf"], record["filename"], "application/pdf")
st.subheader("Send certificates to students")
st.write(
    "Send each student a personalized email "
    "with their own certificate attached."
)

try:
    sender = str(st.secrets["email"]["sender"]).strip()
    app_password = str(
        st.secrets["email"]["app_password"]
    ).replace(" ", "")

    email_configured = bool(sender and app_password)

except (FileNotFoundError, KeyError):
    email_configured = False
    sender = ""
    app_password = ""

if not email_configured:
    st.warning(
        "Check the email settings in .streamlit/secrets.toml, "
        "then restart Streamlit."
    )

else:
    st.write("Sender:", sender)

    recipients = pd.DataFrame([
        {
            "Name": item["student"]["Name"],
            "Email": item["student"]["Email"],
            "Certificate": item["filename"],
        }
        for item in successful
    ])

    st.dataframe(recipients, hide_index=True)

    confirmed = st.checkbox(
        "I checked the recipients and authorize sending these emails."
    )

    if st.button(
        "Send certificates",
        disabled=not confirmed,
    ):
        results = []
        progress = st.progress(0)

        for position, item in enumerate(successful, start=1):
            student = item["student"]

            try:
                send_certificate(
                    sender=sender,
                    app_password=app_password,
                    recipient=student["Email"],
                    subject=render_email(
                        subject_template,
                        student,
                    ),
                    body=render_email(
                        body_template,
                        student,
                    ),
                    certificate_pdf=item["pdf"],
                    filename=item["filename"],
                )

                status = "Accepted by Gmail"

            except Exception:
                status = (
                    "Not confirmed — check Gmail Sent "
                    "before retrying"
                )

            results.append({
                "Name": student["Name"],
                "Email": student["Email"],
                "Status": status,
            })

            progress.progress(position / len(successful))

        st.subheader("Sending results")

        results_table = pd.DataFrame(results)
        st.dataframe(results_table, hide_index=True)

        st.download_button(
            "Download sending report",
            data=results_table.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name="sending_report.csv",
            mime="text/csv",
        )

        st.info(
            "Gmail acceptance does not confirm inbox delivery. "
            "Clicking Send certificates again submits the batch again."
        )