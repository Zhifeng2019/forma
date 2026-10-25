from html import escape


def product_document(name: str, brief: str) -> str:
    return f'''# {name} — Product Description

## Vision
{name} turns a clear user need into a focused, friendly digital experience.

## The opportunity
{brief}

## Primary users
- People who value a guided, low-friction workflow.
- Teams that need a shared, visible source of truth.

## Core experience
1. Understand the current situation at a glance.
2. Take the next useful action without hunting through navigation.
3. Receive clear feedback and retain a history of progress.

## First-release scope
- Responsive overview and primary workflow.
- Purposeful sample data that demonstrates the complete experience.
- Accessible controls, empty states, and mobile layouts.

## Success criteria
A first-time user can understand the product and complete its primary action in under two minutes.
'''


def design_document(name: str, backend_mode: str = 'static', backend_reason: str = '') -> str:
    connected = backend_mode == 'fastapi'
    frontend = ('Semantic HTML, modern CSS, and dependency-free JavaScript. Server requests use the injected '
                'Forma.api bridge, which selects the correct private-preview or published API route.') if connected else (
                'Semantic HTML, modern CSS, and dependency-free JavaScript for a portable static release.')
    backend = ('A dedicated FastAPI service exposes product operations beneath `/api`, including `/api/health`. '
               'Each application has an isolated Python environment, versioned source, an on-demand process, '
               'and an application-local SQLite database when persistence is needed.') if connected else (
               'No product backend is required. Forma still persists builder versions and deployment metadata; '
               'product data can remain in local browser storage.')
    return f'''# {name} — Experience Design

## Design direction
Quiet confidence: warm neutral surfaces, crisp typography, one expressive accent, and generous spacing. Information hierarchy comes from scale and rhythm rather than decoration.

## Information architecture
- **Overview** — current status, key metrics, and recommended next action.
- **Workspace** — the primary user workflow and its supporting context.
- **Activity** — a readable history of meaningful changes.

## System
- 8px spacing grid, 14–18px corner radii.
- Minimum 44px touch targets and visible keyboard focus.
- Responsive single-column composition below 720px.

## Frontend
{frontend}

## Backend contract
{backend}

## Architecture decision
**{'FastAPI backend' if connected else 'Frontend only'}** — {backend_reason or 'Selected when the project was created.'}
'''


def plan_document(name: str, backend_mode: str = 'static') -> str:
    connected = backend_mode == 'fastapi'
    foundation = ('Build the responsive shell, visual system, FastAPI health endpoint, and shared data view. '
                  '**Shareable outcome:** a complete page reading live data from its own API.') if connected else (
                  'Build the responsive shell, visual system, navigation, and meaningful overview. '
                  '**Shareable outcome:** a complete landing and dashboard experience.')
    workflow = ('Add the main server-backed interaction, SQLite persistence, validation, error handling, and feedback. '
                '**Shareable outcome:** a functional end-to-end user journey.') if connected else (
                'Add the main interaction, persistent local state, validation, filtering, and feedback. '
                '**Shareable outcome:** a functional end-to-end user journey.')
    verification = ('Check valid HTML and Python, API health, CRUD behavior, persistence across preview and publishing, '
                    'responsive layout, and a complete preview.') if connected else (
                    'Check valid HTML, working interactions, responsive layout, and a complete preview.')
    return f'''# {name} — Implementation Plan

## Phase 1 · Foundation
{foundation}

## Phase 2 · Core workflow
{workflow}

## Phase 3 · Polish & release
Refine responsive behavior, accessibility, motion, empty states, and final content. **Shareable outcome:** a release candidate ready for review.

## Verification
{verification}
'''


def _js_name(name: str) -> str:
    return escape(name)


def application_html(name: str, brief: str, phase: int = 1, feedback: str = '') -> str:
    safe_name = escape(name)
    short_brief = escape(brief[:220])
    interactive = phase >= 2
    return f'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_name}</title><style>
:root{{--ink:#1c2823;--muted:#718078;--paper:#f5f6f1;--card:#fff;--line:#e2e7df;--green:#256b4b;--lime:#d9f99d;--shadow:0 12px 40px #23352a0a}}*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif;color:var(--ink);background:var(--paper)}}button,input{{font:inherit}}button{{cursor:pointer}}.app{{max-width:1240px;margin:auto;padding:24px 36px 50px}}nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:58px}}.brand{{display:flex;gap:10px;align-items:center;font-weight:800;font-size:19px;letter-spacing:-.5px}}.logo{{width:32px;height:32px;border-radius:10px;background:var(--ink);color:var(--lime);display:grid;place-items:center}}.navlinks{{display:flex;gap:26px;color:var(--muted);font-size:13px}}.avatar{{width:36px;height:36px;border-radius:50%;background:#dce9df;display:grid;place-items:center;font-weight:700}}.hero{{display:grid;grid-template-columns:1.3fr .7fr;gap:40px;align-items:end;margin-bottom:34px}}.eyebrow{{color:var(--green);font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase}}h1{{font-size:clamp(38px,5vw,64px);line-height:1.02;letter-spacing:-3px;max-width:720px;margin:14px 0 20px}}.hero p{{color:var(--muted);max-width:570px;font-size:16px}}.actions{{display:flex;gap:10px;margin-top:24px}}.primary,.secondary{{border:0;border-radius:12px;padding:12px 18px;font-weight:700}}.primary{{background:var(--ink);color:white}}.secondary{{background:white;border:1px solid var(--line);color:var(--ink)}}.pulse{{background:var(--lime);border-radius:20px;padding:25px;min-height:155px;display:flex;flex-direction:column;justify-content:space-between}}.pulse small{{font-weight:700}}.pulse strong{{font-size:37px;letter-spacing:-2px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:var(--shadow)}}.metric{{color:var(--muted);font-size:12px}}.value{{font-size:30px;font-weight:750;letter-spacing:-1px;margin:8px 0}}.trend{{color:var(--green);font-size:12px}}.workspace{{margin-top:16px;display:grid;grid-template-columns:1.4fr .6fr;gap:16px}}.section-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}}h2{{font-size:17px;margin:0;letter-spacing:-.4px}}.item{{display:flex;align-items:center;gap:13px;padding:14px 0;border-top:1px solid var(--line)}}.dot{{width:9px;height:9px;border-radius:50%;background:#87aa91;flex:none}}.item div{{flex:1}}.item strong{{display:block;font-size:13px}}.item small{{color:var(--muted)}}.tag{{background:#eff3eb;padding:4px 9px;border-radius:20px;font-size:10px;color:var(--green)}}.progress{{height:8px;border-radius:8px;background:#edf0e9;overflow:hidden;margin:14px 0}}.progress i{{display:block;height:100%;width:72%;background:var(--green);border-radius:8px}}.note{{color:var(--muted);font-size:12px}}.toast{{position:fixed;bottom:24px;left:50%;transform:translate(-50%,20px);background:var(--ink);color:white;padding:12px 18px;border-radius:12px;opacity:0;transition:.2s;pointer-events:none}}.toast.show{{opacity:1;transform:translate(-50%,0)}}:focus-visible{{outline:3px solid #8bbf9f;outline-offset:3px}}@media(max-width:760px){{.app{{padding:20px}}.navlinks{{display:none}}nav{{margin-bottom:36px}}.hero,.workspace{{grid-template-columns:1fr}}.grid{{grid-template-columns:1fr}}h1{{letter-spacing:-2px}}.pulse{{min-height:120px}}}}
</style></head><body><main class="app"><nav><div class="brand"><span class="logo">✦</span>{safe_name}</div><div class="navlinks"><span>Overview</span><span>Workspace</span><span>Activity</span></div><div class="avatar">YOU</div></nav>
<section class="hero"><div><span class="eyebrow">Your workspace, in focus</span><h1>Make good work<br>feel effortless.</h1><p>{short_brief}</p><div class="actions"><button class="primary" id="newItem">Create new item&nbsp; →</button><button class="secondary" id="tour">Quick tour</button></div></div><aside class="pulse"><small>WEEKLY MOMENTUM</small><strong>+24.8%</strong><span>You're ahead of last week. Keep going.</span></aside></section>
<section class="grid"><article class="card"><span class="metric">ACTIVE PROJECTS</span><div class="value">12</div><span class="trend">↗ 3 this week</span></article><article class="card"><span class="metric">COMPLETED</span><div class="value" id="completed">48</div><span class="trend">↗ 18% from last month</span></article><article class="card"><span class="metric">FOCUS TIME</span><div class="value">26.4h</div><span class="trend">Best week yet</span></article></section>
<section class="workspace"><article class="card"><div class="section-head"><h2>Priority workspace</h2><span class="tag">Up to date</span></div><div id="items"><div class="item"><i class="dot"></i><div><strong>Refine the core experience</strong><small>Today · Product</small></div><span class="tag">In progress</span></div><div class="item"><i class="dot"></i><div><strong>Review customer insights</strong><small>Tomorrow · Research</small></div><span class="tag">Planned</span></div><div class="item"><i class="dot"></i><div><strong>Share the weekly update</strong><small>Friday · Team</small></div><span class="tag">Planned</span></div></div></article><aside class="card"><h2>Weekly goal</h2><div class="value">18 / 25</div><div class="progress"><i></i></div><p class="note">Seven more items to reach your goal. You're building a steady rhythm.</p><hr style="border:0;border-top:1px solid var(--line);margin:22px 0"><h2>Next milestone</h2><p class="note">Release review<br><strong style="color:var(--ink)">Friday, 3:00 PM</strong></p></aside></section></main><div class="toast" id="toast" role="status"></div><script>
const toast=(text)=>{{const el=document.getElementById('toast');el.textContent=text;el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2200)}};
document.getElementById('tour').onclick=()=>toast('Start with a new item, then track your momentum here.');
const state=JSON.parse(localStorage.getItem('forma-app-state')||'{{"items":[]}}');
const render=()=>{{const root=document.getElementById('items');state.items.forEach((text)=>{{const row=document.createElement('div');row.className='item';row.innerHTML='<i class="dot"></i><div><strong></strong><small>Just now · Personal</small></div><span class="tag">New</span>';row.querySelector('strong').textContent=text;root.prepend(row)}});document.getElementById('completed').textContent=48+state.items.length}};render();
document.getElementById('newItem').onclick=()=>{{const text=prompt('What would you like to work on?');if(text&&text.trim()){{state.items.unshift(text.trim().slice(0,100));localStorage.setItem('forma-app-state',JSON.stringify(state));location.reload()}}}};
</script></body></html>''' if interactive else f'''<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_name}</title><style>body{{margin:0;background:#f5f6f1;color:#1c2823;font:15px system-ui}}main{{max-width:1100px;margin:auto;padding:32px}}nav{{font-weight:800;font-size:20px}}section{{padding:110px 0 70px;max-width:800px}}small{{color:#256b4b;font-weight:800;letter-spacing:2px}}h1{{font-size:clamp(46px,7vw,82px);line-height:1;letter-spacing:-4px;margin:22px 0}}p{{color:#718078;font-size:18px;line-height:1.7}}button{{background:#1c2823;color:white;border:0;border-radius:12px;padding:15px 22px;font-weight:700}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}article{{background:white;padding:24px;border:1px solid #e2e7df;border-radius:18px}}@media(max-width:650px){{.cards{{grid-template-columns:1fr}}h1{{letter-spacing:-2px}}}}</style></head><body><main><nav>✦ &nbsp;{safe_name}</nav><section><small>A CLEARER WAY FORWARD</small><h1>Make good work feel effortless.</h1><p>{short_brief}</p><button onclick="document.getElementById('more').scrollIntoView({{behavior:'smooth'}})">Explore the workspace →</button></section><div class="cards" id="more"><article><h3>Focus on what matters</h3><p>A calm overview keeps your next step visible.</p></article><article><h3>Build your rhythm</h3><p>Simple progress signals turn effort into momentum.</p></article><article><h3>Stay in control</h3><p>Your workspace is clear, responsive, and yours.</p></article></div></main></body></html>'''
