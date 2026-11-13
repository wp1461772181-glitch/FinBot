// Tiny argv parser: `--key value`, `--flag`, `--key=value`, plus positionals.
export function parseArgs(argv, { booleans = [] } = {}) {
  const flags = {}; const positional = [];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) { positional.push(arg); continue; }
    const [name, inline] = arg.slice(2).split(/=(.*)/s, 2);
    if (inline !== undefined) flags[name] = inline;
    else if (booleans.includes(name) || i + 1 >= argv.length || argv[i + 1].startsWith("--")) flags[name] = true;
    else { flags[name] = argv[i + 1]; i += 1; }
  }
  return { flags, positional };
}
export const csv = (value, fallback) => (typeof value === "string" ? value.split(",").map((item) => item.trim()).filter(Boolean) : fallback);
