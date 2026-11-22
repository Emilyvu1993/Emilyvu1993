// What the user should do next, per stable error code.
const HINTS: Record<string, string> = {
  PDF_ENCRYPTED: "This PDF is password protected. Remove the password, then add the file again.",
  PDF_CORRUPT: "The file could not be read. Re-export the PDF from its source application.",
  PDF_NOT_FOUND: "The workspace copy of this PDF is missing. Remove it and add it again.",
  NO_TEXT_LAYER: "This looks like a scanned PDF with no selectable text. Only text-based PDFs are supported.",
  INVALID_CONFIG: "Fix the highlighted config value and convert again.",
  INVALID_PAGES: "Use page ranges like 1-3,5. Pages start at 1.",
  TABLE_NOT_FOUND: "Try a different Table strategy (Text for borderless tables) or adjust the page range.",
  NO_RECORDS_FOUND: "Your rule matched nothing. Use Test pattern to check it against the PDF text.",
  REGEX_INVALID: "Fix the regular expression. Use Test pattern to try it.",
  FIELD_MISSING: "A mapped source field doesn't exist. Pick a source from the detected columns.",
  TRANSFORM_FAILED: "A value couldn't be transformed. Check the transform or set a default.",
  TEMPLATE_SYNTAX: "Fix the Jinja syntax in the template ({{ field }}, {% if %} … {% endif %}).",
  TEMPLATE_RENDER: "The template uses a variable that isn't mapped. Use the variables listed above the template.",
  TIMEOUT: "Conversion took too long. Narrow the page range or split the PDF.",
  SIDECAR_CRASH: "The converter stopped unexpectedly. It restarts automatically, so try again.",
  SIDECAR_UNAVAILABLE: "The converter could not start. Reinstall the app.",
  STALE_PREVIEW: "The config changed after the preview. Convert again, then save.",
  JOB_NOT_FOUND: "The preview expired. Convert again.",
  BUSY: "Wait for the current conversion to finish.",
};

export const errorHint = (code: string) => HINTS[code];
