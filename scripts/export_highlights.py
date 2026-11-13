"""Export public-only, self-contained viewing pages from completed local games."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHOICES = [(3, '第四天的转折', '观察连续几天的投票之后，大家如何判断最后的局面。'),
           (6, '失去预言家之后', '第一天的放逐改变了信息结构，之后的判断值得细看。'),
           (5, '三天短局', '节奏紧凑；可与第6局对照：身份布局相同，模型配置互换。')]


def export():
    games = []
    for number, title, intro in CHOICES:
        path = ROOT/f'artifacts/codex-quartet-v1/codex-quartet-18000-{number:02d}.private.json'
        trial = json.loads(path.read_text())
        if trial['status'] != 'finished':
            raise ValueError('Only completed games may be exported.')
        events = [dict(e) for e in trial['game']['events'] if e['audience'] == 'public' and e['kind'] != 'game_over']
        # Keep only public event text, not private messages, tools, notes or traces.
        events = [{k: e[k] for k in ('kind', 'day', 'phase', 'text', 'seat') if k in e} for e in events]
        configs = {p['config']['seat']: p['config'] for p in trial['players']}
        players = [{'seat': p['seat'], 'role': p['role'],
                    'model': configs[p['seat']]['model'].removeprefix('gpt-6.1-')+'/'+configs[p['seat']]['effort']}
                   for p in trial['game']['players']]
        games.append({'number': number, 'title': title, 'intro': intro, 'events': events,
                      'players': players, 'winner': trial['game']['winner']})
    data = json.dumps(games, ensure_ascii=False).replace('<', '\\u003c')
    html = TEMPLATE.replace('__GAMES__', data)
    target = ROOT/'artifacts/highlights/index.html'
    target.parent.mkdir(parents=True, exist_ok=True); target.write_text(html)
    print(target)


TEMPLATE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>狼人杀 · 精选回放</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#10141b;color:#e8edf4}*{box-sizing:border-box}body{margin:0 auto;max-width:1040px;padding:22px}h1{font-size:24px;margin:0 0 8px}p{color:#b3c0d1;line-height:1.6}button,select,input{font:inherit}button,select{border:1px solid #3b4a60;border-radius:9px;background:#1b2432;color:inherit;padding:9px 13px;cursor:pointer}button:hover{background:#2c3c53}button.active{border-color:#e7b35b;color:#ffd48a}nav,.controls{display:flex;gap:8px;flex-wrap:wrap;margin:15px 0}.controls{align-items:center;position:sticky;top:0;background:#10141bf5;padding:12px 0;z-index:1}.players{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-bottom:15px}.player{padding:10px 6px;text-align:center;background:#19212e;border-radius:9px;font-size:12px}.player b{display:block;font-size:17px}.player small{display:block;margin-top:5px;color:#c4a96e}.record{padding:14px 16px;border-left:3px solid #34445a;background:#19212a;margin:9px 0;border-radius:6px;scroll-margin-top:90px}.record.current{border-color:#ffbf59;background:#283245}.meta{font-size:12px;color:#9eb1c9;margin-bottom:8px}.speech{white-space:pre-wrap;line-height:1.8;overflow-wrap:anywhere}.judge{color:#bfcbdb;font-size:14px}.spoiler{padding:12px;background:#422c23;border-radius:8px}footer{color:#91a0b3;font-size:12px;margin:24px 0}.empty{padding:20px}#position{font-size:13px;color:#b6c5d8}@media(max-width:600px){body{padding:14px}.players{grid-template-columns:repeat(3,1fr)}h1{font-size:21px}}
</style><h1>狼人杀 · 精选回放</h1><p>只展示本局公开发言与法官记录。身份与结局需要主动揭晓；不包含任何玩家私聊、私有笔记或模型推理。</p><nav id="games"></nav><h2 id="title"></h2><p id="intro"></p><div class="players" id="players"></div>
<div class="controls"><select id="day" aria-label="选择天数"></select><button id="reveal">揭晓身份与结局（剧透）</button><button id="play">逐条播放</button><button id="next">下一条</button><label><input type="checkbox" id="speechOnly">只看发言</label><span id="position"></span></div><div id="spoiler" hidden class="spoiler"></div><main id="events"></main><footer>这是已完成对局的静态回放，不会调用模型或推进新的游戏。默认展示全部公开记录；逐条播放会从当前所选天数的第一条开始。</footer>
<script>
'use strict';const games=__GAMES__;let selected=0,revealed=false,playing=false,timer=null,index=-1,visible=[];
const $=id=>document.getElementById(id);const roles={wolf:'狼人',villager:'村民',seer:'预言家',witch:'女巫',hunter:'猎人',idiot:'白痴'};
const speechKinds=new Set(['speech','campaign','last_words','wolf_speech','tie_speech']);
function stop(){playing=false;clearTimeout(timer);$('play').textContent='逐条播放'}
function choose(n){stop();selected=n;revealed=false;index=-1;const g=games[n];$('title').textContent='第 '+g.number+' 局 · '+g.title;$('intro').textContent=g.intro;$('day').replaceChildren();for(const d of ['全部',...new Set(g.events.map(e=>e.day))]){let o=document.createElement('option');o.value=d;o.textContent=d==='全部'?'全部天数':'第 '+d+' 天';$('day').append(o)}renderPlayers();render();for(const [i,b] of [...$('games').children].entries())b.classList.toggle('active',i===n)}
function renderPlayers(){const g=games[selected];$('players').replaceChildren();for(const p of g.players){let e=document.createElement('div');e.className='player';let b=document.createElement('b');b.textContent=p.seat+'号';e.append(b,document.createTextNode(p.model));if(revealed){let s=document.createElement('small');s.textContent=roles[p.role];e.append(s)}$('players').append(e)}$('spoiler').hidden=!revealed;$('spoiler').textContent='最终胜方：'+(g.winner==='wolves'?'狼人阵营':'好人阵营');$('reveal').textContent=revealed?'隐藏身份与结局':'揭晓身份与结局（剧透）'}
function render(){const d=$('day').value;visible=games[selected].events.filter(e=>(d==='全部'||String(e.day)===d)&&(!$('speechOnly').checked||speechKinds.has(e.kind)));$('events').replaceChildren();for(const [i,e] of visible.entries()){const row=document.createElement('article');row.className='record';row.id='event-'+i;const meta=document.createElement('div');meta.className='meta';meta.textContent='第 '+e.day+' 天 · '+e.phase+(e.seat?' · '+e.seat+'号':' · 法官');const text=document.createElement('div');text.className=speechKinds.has(e.kind)?'speech':'speech judge';text.textContent=e.text;row.append(meta,text);$('events').append(row)}if(!visible.length)$('events').textContent='这一筛选下没有公开记录。';$('position').textContent=visible.length+' 条公开记录'}
function showNext(){if(index+1>=visible.length){stop();return}index++;for(const [i,e] of [...$('events').children].entries()){e.hidden=i>index;e.classList.toggle('current',i===index)}$('position').textContent=(index+1)+' / '+visible.length;$('event-'+index)?.scrollIntoView({behavior:'smooth',block:'nearest'})}
function tick(){showNext();if(playing)timer=setTimeout(tick,Math.min(15000,Math.max(3000,(visible[index]?.text.length||20)*65)))}
for(const [i,g] of games.entries()){let b=document.createElement('button');b.textContent='第 '+g.number+' 局 · '+g.title;b.onclick=()=>choose(i);$('games').append(b)}
$('day').onchange=$('speechOnly').onchange=()=>{stop();index=-1;render()};$('reveal').onclick=()=>{revealed=!revealed;renderPlayers()};$('next').onclick=()=>{stop();showNext()};$('play').onclick=()=>{if(playing){stop();return}if(index>=visible.length-1)index=-1;playing=true;$('play').textContent='暂停';tick()};choose(0);
</script></html>'''

if __name__ == '__main__':
    export()
