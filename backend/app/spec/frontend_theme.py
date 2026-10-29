"""Reviewed responsive design tokens shared by AppSpec frontend formats."""

APPSPEC_CSS = '''
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17251f;background:#f3f6f4;font-synthesis:none;--ink:#17251f;--muted:#637269;--paper:#f3f6f4;--surface:#fff;--line:#dce4de;--accent:#245d49;--accent-hover:#194a39;--accent-soft:#e6f0ea;--danger:#a23b32;--danger-soft:#fff0ed;--success:#286247;--success-soft:#eaf5ed;--shadow:0 16px 45px rgba(28,52,39,.06)}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;min-width:320px;background:var(--paper)}
button,input,textarea{font:inherit}
button{min-height:42px;cursor:pointer;border:0;border-radius:11px;padding:10px 16px;font-weight:700;transition:background .16s ease,border-color .16s ease}
button:disabled{cursor:not-allowed;opacity:.5}
button:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid #8ebc9f;outline-offset:2px}
button.primary{background:var(--accent);color:#fff}
button.primary:hover:not(:disabled){background:var(--accent-hover)}
button.secondary{background:#fff;color:var(--ink);border:1px solid var(--line)}
button.secondary:hover:not(:disabled){border-color:#aabbb0;background:#fafcfb}
.app{max-width:1180px;margin:0 auto;padding:30px 32px 48px}
nav{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:38px}
.brand{display:flex;align-items:center;gap:11px;min-width:0;font-size:19px;font-weight:800;letter-spacing:-.025em;overflow-wrap:anywhere}
.brand-mark{display:grid;place-items:center;flex:0 0 34px;width:34px;height:34px;border-radius:11px;background:var(--ink);color:#d8eadf}
.status{display:inline-flex;align-items:center;gap:8px;flex:none;color:var(--muted);font-size:12px;font-weight:650}
.status-dot{width:8px;height:8px;border-radius:50%;background:#c18a3b}
.status.online .status-dot{background:#3a9267}
.status.offline .status-dot{background:var(--danger)}
.hero{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:34px;align-items:end;margin-bottom:28px}
.hero-copy{min-width:0}
.eyebrow{margin:0 0 10px;color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}
.hero h1{max-width:820px;margin:0;font-size:clamp(36px,5vw,58px);line-height:1.06;letter-spacing:-.045em;overflow-wrap:anywhere}
.hero-workflow{max-width:740px;margin:18px 0 0;color:var(--muted);font-size:16px;line-height:1.7;white-space:pre-line;overflow-wrap:anywhere}
.metric{min-width:0;padding:23px;border:1px solid #cfded3;border-radius:19px;background:var(--accent-soft)}
.metric-label{display:block;color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}
.metric strong{display:block;margin:15px 0 4px;font-size:38px;line-height:1;letter-spacing:-.04em}
.metric small{color:var(--muted);overflow-wrap:anywhere}
.alert{display:flex;align-items:flex-start;gap:10px;margin:0 0 18px;padding:13px 15px;border-radius:12px;font-size:14px;line-height:1.5;overflow-wrap:anywhere}
.alert.error{border:1px solid #efc8bf;background:var(--danger-soft);color:var(--danger)}
.alert.success{border:1px solid #c9e2d0;background:var(--success-soft);color:var(--success)}
.workspace{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:20px;align-items:start}
.panel{min-width:0;padding:24px;border:1px solid var(--line);border-radius:20px;background:var(--surface);box-shadow:var(--shadow)}
.panel-header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:22px}
.panel-header h2,.context-panel h2{margin:0;font-size:20px;letter-spacing:-.025em;overflow-wrap:anywhere}
.count-badge{flex:none;padding:6px 10px;border-radius:999px;background:#f0f4f1;color:var(--muted);font-size:12px;font-weight:700}
.record-form{margin:0 0 25px;padding-bottom:25px;border-bottom:1px solid var(--line)}
.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.field{display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--ink);font-size:13px;font-weight:650}
.field-wide{grid-column:1/-1}
.field-label{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
.field-note{color:var(--muted);font-size:11px;font-weight:500}
.field input:not([type=checkbox]),.field textarea{width:100%;min-width:0;min-height:44px;padding:11px 12px;border:1px solid #cfd9d2;border-radius:10px;background:#fbfcfb;color:var(--ink);line-height:1.45}
.field textarea{min-height:96px;resize:vertical}
.field input::placeholder,.field textarea::placeholder{color:#8b978f}
.field input:disabled,.field textarea:disabled{background:#f0f2f0;color:#879188}
.field-checkbox{display:grid;grid-template-columns:20px minmax(0,1fr);align-items:center;gap:10px;min-height:44px;padding:10px 12px;border:1px solid #cfd9d2;border-radius:10px;background:#fbfcfb}
.field-checkbox input{width:18px;height:18px;margin:0;accent-color:var(--accent)}
.form-actions{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:18px}
.form-actions small{color:var(--muted);line-height:1.5}
.items{display:grid;gap:12px}
.item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;align-items:start;padding:17px;border:1px solid var(--line);border-radius:14px;background:#fcfdfc}
.item-content{min-width:0}
.item-title{display:block;margin-bottom:12px;font-size:16px;line-height:1.4;overflow-wrap:anywhere}
.item-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px 16px}
.item-field{display:flex;flex-direction:column;gap:3px;min-width:0;color:var(--muted);font-size:12px;line-height:1.45;overflow-wrap:anywhere}
.item-field b{color:#4c5d52;font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase}
.item-actions{display:flex;gap:7px}
.icon-button{min-width:36px;min-height:36px;padding:7px 10px;border:1px solid var(--line);background:#fff;color:var(--muted)}
.icon-button.delete:hover:not(:disabled){border-color:#e4b5ac;background:var(--danger-soft);color:var(--danger)}
.context-panel{box-shadow:none}
.context-panel p:not(.eyebrow){color:var(--muted);font-size:14px;line-height:1.7;white-space:pre-line;overflow-wrap:anywhere}
.context-panel button{width:100%;margin-top:10px}
.context-note{display:block;margin-top:15px;color:var(--muted);font-size:12px;line-height:1.6}
.empty-state{padding:32px 22px;border:1px dashed #bdccc1;border-radius:14px;background:#fafcfa;text-align:center}
.empty-state strong{display:block;margin-bottom:7px;font-size:15px;overflow-wrap:anywhere}
.empty-state p{max-width:420px;margin:0 auto;color:var(--muted);font-size:13px;line-height:1.6;overflow-wrap:anywhere}
.loading-state{color:var(--muted)}
@media(max-width:860px){.hero,.workspace{grid-template-columns:minmax(0,1fr)}.metric{max-width:none}.context-panel button{width:auto}.hero{gap:20px}}
@media(max-width:600px){.app{padding:20px 16px 32px}nav{align-items:flex-start;margin-bottom:30px}.brand{font-size:17px}.status{font-size:11px}.hero h1{font-size:36px}.hero-workflow{font-size:15px}.panel{padding:18px;border-radius:16px}.form-grid{grid-template-columns:minmax(0,1fr)}.field-wide{grid-column:auto}.panel-header{align-items:center}.form-actions{align-items:stretch;flex-direction:column}.form-actions button{width:100%}.item{grid-template-columns:minmax(0,1fr)}.item-actions{justify-content:flex-end}.item-fields{grid-template-columns:minmax(0,1fr)}}
@media(prefers-reduced-motion:reduce){button{transition:none}}
'''
