#!/usr/bin/env node
"use strict";
// Offline golden tests against the proposed manifest. No browser or network interaction.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const base = path.join(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(base, "data", "ok-ai-faq.v1.json"), "utf8"));
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "ok-ai-faq-golden.v1.json"), "utf8"));
function normalize(question) {
  if (typeof question !== "string" || !question.length || question.length > 240 ||
      /[\x00-\x1f\x7f]/.test(question)) return "";
  return question.trim().toLowerCase().replace(/\s+/g, " ").replace(/[?.!]$/, "").trim();
}
assert.equal(fixture.schema_version, 1);
const answers = new Map();
for (const entry of manifest.entries) {
  for (const variant of entry.variants) {
    const key = normalize(variant);
    assert.ok(key && !answers.has(key), "Duplicate normalized fixture key");
    answers.set(key, entry);
  }
}
let passed = 0;
for (const test of fixture.cases) {
  const entry = answers.get(normalize(test.question));
  const actualId = entry ? entry.question_id : null;
  assert.equal(actualId, test.expected_id, test.id + ": unexpected routing");
  const actualAnswer = entry ? entry.answer : manifest.default_response;
  if (entry) {
    assert.ok(entry.sources.length > 0, test.id + ": missing citation");
    assert.ok(entry.sources.every(s => s.url.includes("/blob/" + s.commit_sha + "/")), test.id + ": unpinned source");
  } else {
    assert.equal(actualAnswer, manifest.default_response, test.id + ": wrong refusal");
  }
  passed++;
}
console.log("Golden tests PASS (" + passed + " cases; static FAQ routing and refusal)");
console.log("Note: does not exercise the deployed widget, DOM XSS handling, CI or network.");
