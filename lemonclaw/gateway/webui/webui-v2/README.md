# webui-v2

Preact + Vite frontend for the LemonClaw WebUI.

## Commands

- `npm run dev` — start the local Vite dev server
- `npm run build` — build the production bundle into `../static`
- `npm run preview` — preview the Vite build locally

## Dependency policy

This frontend intentionally uses **pinned versions** in `package.json` instead of broad ranges.
The goal is reproducible builds and fewer surprises when `npm install` refreshes the lockfile.

Current validated set:

- `vite`: `8.0.0-beta.16`
- `@preact/preset-vite`: `2.10.3`
- `preact`: `10.27.2`
- `@preact/signals`: `2.8.1`
- `typescript`: `5.9.3`
- `dompurify`: `3.3.1`
- `marked`: `17.0.4`
- `highlight.js`: `11.11.1`
- `@babel/core`: `7.29.0`

### Why `@babel/core` is pinned

`@preact/preset-vite` uses a Babel transform path in this project.
We enable that path on purpose in `vite.config.ts` to avoid the Vite 8 beta warning about the deprecated `esbuild` option and the switch to `oxc`.

### Why versions are pinned

This project currently depends on a specific combination of:

- Vite 8 beta behavior
- `@preact/preset-vite` 2.10.x behavior
- a Babel fallback workaround in `vite.config.ts`

Using wide semver ranges here makes it too easy to pull a new toolchain combination that builds differently or reintroduces warnings.

## Build output

The Python gateway serves static files from `lemonclaw/gateway/webui/static`.
Because of that, `vite.config.ts` writes production builds directly into that directory instead of treating `dist/` as the deployed artifact.

If you change the build path, also check the Python side:

- `lemonclaw/gateway/server.py`
- `lemonclaw/gateway/webui/routes.py`

## Bundle size notes

The chat renderer uses `highlight.js/lib/core` plus a small set of registered languages.
Do not switch back to the top-level `highlight.js` import unless you are okay with a much larger bundle.

## Upgrade guidance

If you want to refresh the toolchain, prefer one of these paths:

1. stay on the current pinned set and only update after a clean rebuild succeeds;
2. move to a fully stable Vite + Preact preset combination and then remove the Babel workaround.

After any dependency change, always run:

```bash
npm run build
```

and confirm the generated files in `../static` still load correctly through the gateway.
