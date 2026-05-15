#!/usr/bin/env node
// Wrapper for tavily-search to use from shell scripts

const { spawn } = require('child_process');
const path = require('path');

const apiKey = process.env.TAVILY_API_KEY;
if (!apiKey) {
  console.error('Missing TAVILY_API_KEY');
  process.exit(1);
}

const args = process.argv.slice(2);
const script = path.join(__dirname, '../.openclaw/extensions/tavily-search/scripts/search.mjs');

const proc = spawn('node', [script, ...args], {
  env: { ...process.env, TAVILY_API_KEY: apiKey },
  stdio: 'inherit'
});

proc.on('exit', (code) => process.exit(code || 0));