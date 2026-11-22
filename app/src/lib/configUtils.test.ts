import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG, DEFAULT_SECTIONS_RULE, GLYPH_PRESETS, SECTION_FIELDS } from "../types/domain";
import { templateVariables, availableSources, conversionKey, fieldsFromColumns, stableStringify, templateFromFields, toIdentifier } from "./configUtils";

describe("configUtils", () => {
  it("stableStringify sorts keys and drops undefined", () => {
    expect(stableStringify({ b: 1, a: { d: 2, c: undefined } })).toBe('{"a":{"d":2},"b":1}');
  });
  it("conversionKey ignores name/id/version", () => {
    const a = { ...DEFAULT_CONFIG, name: "A" };
    const b = { ...DEFAULT_CONFIG, name: "B", id: "x", version: 3 };
    expect(conversionKey(a)).toBe(conversionKey(b));
    expect(conversionKey({ ...a, template: { record: "x" } })).not.toBe(conversionKey(a));
  });
  it("toIdentifier handles Vietnamese, spaces, digits", () => {
    expect(toIdentifier("Số tiền (VND)")).toBe("so_tien_vnd");
    expect(toIdentifier("Ngày GD")).toBe("ngay_gd");
    expect(toIdentifier("2024")).toBe("f_2024");
  });
  it("fieldsFromColumns dedupes targets", () => {
    expect(fieldsFromColumns(["Amount", "amount"]).map((f) => f.target)).toEqual(["amount", "amount_"]);
  });
  it("table preset escapes cells", () => {
    const t = templateFromFields(fieldsFromColumns(["Date", "Desc"]), "table");
    expect(t.header).toBe("| Date | Desc |\n| --- | --- |");
    expect(t.record).toBe("| {{ date | md }} | {{ desc | md }} |");
  });
  it("block sources come from named groups and field patterns", () => {
    const c = { ...DEFAULT_CONFIG, extraction: { type: "block" as const, start_pattern: "^No (?P<inv>\\d+)", field_patterns: { total: "T: (.+)" } } };
    expect(availableSources(c, [])).toEqual(["inv", "total", "_raw", "_page"]);
  });
  it("sections expose fixed fields as sources and template variables", () => {
    const c = { ...DEFAULT_CONFIG, extraction: { ...DEFAULT_SECTIONS_RULE } };
    expect(availableSources(c, [])).toEqual([...SECTION_FIELDS, "_page"]);
    expect(templateVariables(c)).toEqual(SECTION_FIELDS);
    expect(templateVariables({ ...c, fields: [{ source: "title", target: "t" }] })).toEqual(["t"]);
  });
  it("astro preset carries its own angle convention and keeps Sid.t as printed", () => {
    const p = GLYPH_PRESETS.find((x) => x.id === "astro")!;
    expect(p.angle).toEqual({ font: "adienst", skip_columns: ["Sid.t"] });
    expect(Object.keys(p.map)).toEqual(["adienst"]);          // font name in the map and in the angle rule agree
  });
  it("angle convention changes the conversion key (stale-preview guard)", () => {
    const base = { ...DEFAULT_CONFIG };
    const withAngle = { ...base, extraction: { ...(base.extraction as object), angle_format: { font: "adienst" } } } as typeof base;
    expect(conversionKey(withAngle)).not.toBe(conversionKey(base));
  });
});
