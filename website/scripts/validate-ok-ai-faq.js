#!/usr/bin/env node
"use strict";
// OK-205: offline manifest shape and safety checks; --release requires explicit approvals.
// Remote source existence and claim-level truth require separate checks and human review.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const defaultPath = path.join(__dirname, "..", "data", "ok-ai-faq.v1.json");
const statuses = new Set(["proposed", "approved", "expired", "rejected"]);
function normalize(s) {
  if (typeof s !== "string" || !s.length || s.length > 240 || /[\x00-\x1f\x7f]/.test(s)) return "";
  return s.trim().toLowerCase().replace(/\s+/g, " ").replace(/[?.!]$/, "").trim();
}
function validate(doc, release = false, now = new Date()) {
  const errors = [], fail = (m) => errors.push(m);
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) return ["Invalid manifest object"];
  if (doc.schema_version !== 1) fail("Unsupported schema_version");
  if (!Array.isArray(doc.entries) || doc.entries.length === 0) return [...errors, "Missing entries"];
  if (typeof doc.default_response !== "string" || !doc.default_response.trim()) fail("Missing default refusal");
  const ids = new Set(), variants = new Set();
  for (const [i, e] of doc.entries.entries()) {
    const where = "entries[" + i + "]";
    if (!e || typeof e !== "object") { fail(where + ": invalid entry"); continue; }
    if (typeof e.question_id !== "string" || !/^[a-z][a-z0-9-]*$/.test(e.question_id) || ids.has(e.question_id))
      fail(where + ": invalid/duplicate question_id");
    else ids.add(e.question_id);
    if (typeof e.answer !== "string" || !e.answer.trim()) fail(where + ": missing answer");
    if (!Array.isArray(e.variants) || !e.variants.length) fail(where + ": missing variants");
    else for (const q of e.variants) {
      const v = normalize(q);
      if (!v || variants.has(v)) fail(where + ": invalid/duplicate normalized variant");
      else variants.add(v);
    }
    if (!Array.isArray(e.sources) || !e.sources.length) fail(where + ": missing sources");
    else for (const s of e.sources) {
      if (!s || !/^[-\w.]+\/[-\w.]+$/.test(s.repository || "") ||
        !/^[a-f0-9]{40}$/.test(s.commit_sha || "") ||
        typeof s.path !== "string" || !/^[a-zA-Z0-9_./-]+$/.test(s.path) ||
        s.path.startsWith("/") || s.path.split("/").includes("..") ||
        s.url !== "https://github.com/" + s.repository + "/blob/" + s.commit_sha + "/" + s.path)
        fail(where + ": invalid immutable source metadata");
    }
    const r = e.review;
    if (!r || !statuses.has(r.status)) { fail(where + ": missing/invalid review status"); continue; }
    if (release) {
      if (r.status !== "approved" || typeof r.owner !== "string" || !r.owner.trim() ||
        !/^\d{4}-\d{2}-\d{2}$/.test(r.reviewed_at || "") ||
        !/^\d{4}-\d{2}-\d{2}$/.test(r.review_due || "") ||
        Number.isNaN(Date.parse(r.reviewed_at)) || Number.isNaN(Date.parse(r.review_due)) ||
        r.reviewed_at > r.review_due || r.review_due < now.toISOString().slice(0,10))
        fail(where + ": not approved, reviewed, or review expired");
    }
  }
  return errors;
}
function selfTest(doc) {
  assert.deepEqual(validate(doc), []);
  const unapproved = JSON.parse(JSON.stringify(doc));
  unapproved.entries[0].review.status = "proposed";
  assert.ok(validate(unapproved, true).some(e => e.includes("not approved")));
  const copy = () => JSON.parse(JSON.stringify(doc));
  let d = copy(); d.entries[1].variants = [d.entries[0].variants[0].toUpperCase()];
  assert.ok(validate(d).some(e => e.includes("duplicate normalized")));
  d = copy(); d.entries[0].sources[0].commit_sha = "main";
  assert.ok(validate(d).some(e => e.includes("source metadata")));
  d = copy(); d.entries[0].question_id = d.entries[1].question_id;
  assert.ok(validate(d).some(e => e.includes("duplicate question_id")));
  for (const q of ["hello\nworld", "x".repeat(241), "", "\u0000"]) assert.equal(normalize(q), "");
  assert.equal(normalize(" What IS ok-local? "), "what is ok-local");
  assert.equal(normalize("what is ok-local??"), "what is ok-local?");
  console.log("Self-test PASS (draft validation, fail-closed release, duplicate variants/IDs, bad SHA, normalization)");
}
const args = process.argv.slice(2);
if (args.some(x => !["--release", "--self-test"].includes(x))) {
  console.error("Usage: node website/scripts/validate-ok-ai-faq.js [--release] [--self-test]");
  process.exit(2);
}
const doc = JSON.parse(fs.readFileSync(defaultPath, "utf8"));
const errors = validate(doc, args.includes("--release"));
if (errors.length) {
  for (const e of errors) console.error("FAIL: " + e);
  process.exit(1);
}
console.log("Manifest validation PASS (" + (args.includes("--release") ? "release" : "draft") + ")");
if (args.includes("--self-test")) selfTest(doc);
