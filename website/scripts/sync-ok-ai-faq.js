#!/usr/bin/env node
"use strict";
// Generate or verify the static FAQ block in the deployed browser asset.
const fs = require("node:fs");
const path = require("node:path");
const base = path.join(__dirname, "..");
const manifest = JSON.parse(fs.readFileSync(path.join(base,"data","ok-ai-faq.v1.json"),"utf8"));
const asset = path.join(base,"assets","ok-ai-lite-preview.js");
const current = fs.readFileSync(asset,"utf8");
const begin = "  // BEGIN GENERATED OK-205 FAQ DATA — edit website/data/ok-ai-faq.v1.json instead.";
const end = "  // END GENERATED OK-205 FAQ DATA";
const normalize = q => q.trim().toLowerCase().replace(/\s+/g," ").replace(/[?.!]$/,"").trim();
const map = {};
for(const entry of manifest.entries) {
  if(entry.review.status !== "approved") throw new Error("Unapproved FAQ entry: "+entry.question_id);
  for(const phrase of entry.variants) {
    const key=normalize(phrase);
    if(Object.prototype.hasOwnProperty.call(map,key)) throw new Error("Duplicate phrase "+key);
    map[key]={answer:entry.answer,sources:entry.sources.map(s=>s.url)};
  }
}
const generated=begin+"\n  var supported = Object.freeze("+JSON.stringify(map,null,2).split("\n").join("\n  ")+");\n  var unsupported = "+JSON.stringify(manifest.default_response)+";\n"+end;
const start=current.indexOf(begin),stop=current.indexOf(end);
if(start<0||stop<start) throw new Error("Generated markers missing");
const output=current.slice(0,start)+generated+current.slice(stop+end.length);
if(process.argv.includes("--check")) {
  if(output!==current) {console.error("FAQ browser asset out of sync with manifest");process.exit(1);}
  console.log("FAQ browser asset synchronized with approved manifest ("+Object.keys(map).length+" phrases)");
} else {
  fs.writeFileSync(asset,output);
  console.log("Generated FAQ browser asset");
}
