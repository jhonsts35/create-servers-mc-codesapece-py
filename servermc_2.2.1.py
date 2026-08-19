#!/usr/bin/env python3
import json, os, re, shutil, subprocess, time, urllib.request, threading, http.server, socketserver
try:
    import psutil
except ImportError:
    psutil=None

BASE_DIR=os.path.dirname(os.path.abspath(__file__))
ESTADO_FILE=os.path.join(BASE_DIR,'.setup_state.json')
SERVER_DIR=os.path.join(BASE_DIR,'minecraft-server')
SERVER_JAR=os.path.join(SERVER_DIR,'server.jar')
SERVER_INFO_FILE=os.path.join(SERVER_DIR,'.server_info.json')
EULA_FILE=os.path.join(SERVER_DIR,'eula.txt')
DASHBOARD_DIR=os.path.join(BASE_DIR,'dashboard')
DASHBOARD_HTML=os.path.join(DASHBOARD_DIR,'index.html')
VERSION_MANIFEST='https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'
USER_AGENT='MinecraftServerSetup/6.0'
DASHBOARD_PORT=8080
VERDE='\033[92m'; AMARILLO='\033[93m'; ROJO='\033[91m'; RESET='\033[0m'

minecraft_process=None
minecraft_lock=threading.Lock()
dashboard_server=None

def cargar_json(r):
    try:
        with open(r,encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def guardar_json(r,d):
    os.makedirs(os.path.dirname(r) or '.',exist_ok=True)
    with open(r,'w',encoding='utf-8') as f:
        json.dump(d,f,indent=2,ensure_ascii=False)

def cargar_estado():
    return cargar_json(ESTADO_FILE)

def guardar_estado(d):
    guardar_json(ESTADO_FILE,d)

def comando_existe(c):
    return shutil.which(c) is not None

def limpiar():
    os.system('clear')

def pausa():
    input('\nPresiona ENTER para continuar...')

def server_info():
    i=cargar_json(SERVER_INFO_FILE)
    m=cargar_estado().get('minecraft',{})
    return (
        i.get('minecraft_version') or m.get('version'),
        i.get('tipo') or m.get('tipo'),
        i.get('plataforma') or m.get('plataforma')
    )

def obtener_ram():
    try:
        return max(1,int(cargar_estado().get('launch',{}).get('ram_gb',8)))
    except:
        return 8

def guardar_ram(r):
    s=cargar_estado()
    s.setdefault('launch',{})['ram_gb']=int(r)
    guardar_estado(s)

def guardar_configuracion(v,t,p):
    s=cargar_estado()
    s['minecraft']={
        'version':v,
        'tipo':t,
        'plataforma':p
    }
    s.setdefault('launch',{'ram_gb':8})
    guardar_estado(s)

def obtener_ip_playit():
    return cargar_estado().get('playit',{}).get('ip')

def guardar_ip_playit(ip):
    s=cargar_estado()
    s['playit']={
        'ip':ip,
        'updated':int(time.time())
    }
    guardar_estado(s)

def propiedades():
    r=os.path.join(SERVER_DIR,'server.properties')
    d={}

    if os.path.exists(r):
        try:
            with open(r,encoding='utf-8',errors='ignore') as f:
                for line in f:
                    line=line.strip()

                    if line and not line.startswith('#') and '=' in line:
                        k,v=line.split('=',1)
                        d[k.strip()]=v.strip()

        except Exception:
            pass

    return d

def guardar_propiedades(changes):
    os.makedirs(SERVER_DIR,exist_ok=True)

    r=os.path.join(SERVER_DIR,'server.properties')
    old=[]
    seen=set()

    if os.path.exists(r):
        with open(r,encoding='utf-8',errors='ignore') as f:
            old=f.read().splitlines()

    out=[]

    for line in old:
        if '=' in line and not line.lstrip().startswith('#'):
            k=line.split('=',1)[0].strip()

            if k in changes:
                out.append(k+'='+str(changes[k]))
                seen.add(k)
                continue

        out.append(line)

    for k,v in changes.items():
        if k not in seen:
            out.append(k+'='+str(v))

    with open(r,'w',encoding='utf-8') as f:
        f.write('\n'.join(out)+'\n')

def lista_archivo(nombre):
    try:
        r=os.path.join(SERVER_DIR,nombre)

        if not os.path.exists(r):
            return []

        with open(r,encoding='utf-8') as f:
            return json.load(f)

    except Exception:
        return []

def nombres_archivo(nombre):
    return [
        x.get('name',x.get('uuid',''))
        for x in lista_archivo(nombre)
    ]

def guardar_linea_consola(linea):
    s=cargar_estado()
    c=s.get('console',[])
    c=c if isinstance(c,list) else []
    c.append(linea.rstrip())
    s['console']=c[-500:]
    guardar_estado(s)

def enviar_comando(cmd):
    global minecraft_process

    with minecraft_lock:
        p=minecraft_process

        if not p or p.poll() is not None or not p.stdin:
            return False

        try:
            p.stdin.write(cmd+'\n')
            p.stdin.flush()
            guardar_linea_consola('> '+cmd)
            return True

        except Exception:
            return False

def detener_servidor():
    global minecraft_process

    with minecraft_lock:
        p=minecraft_process

        if not p or p.poll() is not None or not p.stdin:
            return False,'El servidor ya está apagado'

        try:
            p.stdin.write('stop\n')
            p.stdin.flush()
            guardar_linea_consola('> stop')
            return True,'Comando STOP enviado al servidor'

        except Exception as e:
            return False,f'No se pudo detener el servidor: {e}'

def accion_jugador(accion,nombre):
    nombre=nombre.strip()

    if not re.fullmatch(r'[A-Za-z0-9_]{1,16}',nombre):
        return False,'Nombre inválido'

    comandos={
        'whitelist-add':f'whitelist add {nombre}',
        'whitelist-remove':f'whitelist remove {nombre}',
        'ban':f'ban {nombre}',
        'unban':f'pardon {nombre}',
        'op':f'op {nombre}',
        'deop':f'deop {nombre}'
    }

    if accion not in comandos:
        return False,'Acción inválida'

    if enviar_comando(comandos[accion]):
        return True,'Comando enviado al servidor'

    return False,'El servidor está apagado'

def obtener_ram_sistema():
    if psutil:
        try:
            m=psutil.virtual_memory()

            return {
                'total':round(m.total/2**30,2),
                'used':round(m.used/2**30,2),
                'available':round(m.available/2**30,2),
                'percent':round(m.percent,1)
            }

        except Exception:
            pass

    try:
        d={}

        for l in open('/proc/meminfo'):
            p=l.split()
            d[p[0].rstrip(':')]=int(p[1])*1024

        t=d.get('MemTotal',0)
        a=d.get('MemAvailable',d.get('MemFree',0))
        u=max(0,t-a)

        return {
            'total':round(t/2**30,2),
            'used':round(u/2**30,2),
            'available':round(a/2**30,2),
            'percent':round(u/t*100,1) if t else 0
        }

    except Exception:
        return {
            'total':0,
            'used':0,
            'available':0,
            'percent':0
        }

def extraer_ip_playit(linea):
    for p in [
        r'found minecraft java tunnel:\s*([A-Za-z0-9._-]+)',
        r'minecraft java tunnel:\s*([A-Za-z0-9._-]+)',
        r'([A-Za-z0-9.-]+\.tun\.ply\.gg)'
    ]:
        m=re.search(p,linea,re.I)

        if m:
            return m.group(1).strip()

def dashboard_data():
    v,t,p=server_info()
    m=obtener_ram_sistema()
    s=cargar_estado()

    return {
        'online':minecraft_process is not None and minecraft_process.poll() is None,
        'minecraft':v or 'N/A',
        'type':t or 'N/A',
        'platform':p or 'Vanilla',
        'ram_assigned':obtener_ram(),
        'ram_total':m['total'],
        'ram_used':m['used'],
        'ram_available':m['available'],
        'ram_percent':m['percent'],
        'playit':obtener_ip_playit(),
        'console':'\n'.join(s.get('console',[])[-300:]),
        'properties':propiedades(),
        'whitelist':nombres_archivo('whitelist.json'),
        'banned':nombres_archivo('banned-players.json'),
        'ops':nombres_archivo('ops.json')
    }

def generar_dashboard():
    os.makedirs(DASHBOARD_DIR,exist_ok=True)

    html_doc='''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minecraft Server Dashboard</title>

<style>
*{box-sizing:border-box}
body{
margin:0;
background:radial-gradient(circle at top right,#24114f 0,#101525 28%,#0b0f18 65%);
color:#f1f5f9;
font-family:Arial,Helvetica,sans-serif
}
.wrap{max-width:1500px;margin:auto;padding:30px}
.top{
display:flex;
justify-content:space-between;
align-items:center;
gap:20px;
margin-bottom:25px
}
.title{font-size:30px;font-weight:800}
.subtitle{color:#8f8aaa;margin-top:7px;font-size:15px}
.status{
padding:9px 16px;
border-radius:20px;
background:#17251c;
color:#6dff9b;
font-weight:bold;
white-space:nowrap
}
.grid{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
gap:15px
}
.card{
background:rgba(17,24,32,.88);
border:1px solid #273044;
border-radius:16px;
padding:20px;
margin-bottom:16px;
box-shadow:0 8px 30px rgba(0,0,0,.18)
}
.card h2,.card h3{margin-top:0}
.value{font-size:25px;font-weight:bold}
.bar{
height:14px;
background:#202838;
border-radius:10px;
overflow:hidden;
margin-top:15px
}
.fill{
height:100%;
background:#a855f7;
width:0;
transition:.3s
}
.two{
display:grid;
grid-template-columns:1fr 1fr;
gap:15px
}
@media(max-width:750px){
.two{grid-template-columns:1fr}
}
button,input,select{
background:#0b0f14;
color:#e6edf3;
border:1px solid #334155;
border-radius:9px;
padding:10px
}
button{cursor:pointer}
button:hover{border-color:#a855f7}
.primary{
background:linear-gradient(135deg,#9333ea,#7c3aed);
border-color:#a855f7;
font-weight:bold;
padding:12px 18px
}
.stop-button{
background:linear-gradient(135deg,#dc2626,#991b1b);
border-color:#ef4444;
font-weight:bold;
padding:12px 20px;
color:white
}
.stop-button:hover{
border-color:#ff6b6b;
box-shadow:0 0 15px rgba(239,68,68,.25)
}
.row{
display:flex;
flex-wrap:wrap;
align-items:center
}
.console{
height:280px;
overflow:auto;
background:#070a0d;
padding:15px;
border-radius:10px;
font-family:monospace;
white-space:pre-wrap
}
.tag{
display:inline-block;
background:#202832;
border-radius:15px;
padding:5px 9px;
margin:3px
}
.muted{color:#9299b8}
.properties-header{
display:flex;
justify-content:space-between;
align-items:center;
gap:20px;
margin-bottom:20px
}
.properties-actions{
display:flex;
gap:8px;
flex-wrap:wrap
}
.props{
display:grid;
grid-template-columns:1fr 1fr;
gap:8px 20px
}
@media(max-width:900px){
.props{grid-template-columns:1fr}
}
.property{
min-height:64px;
display:flex;
justify-content:space-between;
align-items:center;
gap:18px;
padding:13px 18px;
border:1px solid #273044;
border-radius:14px;
background:linear-gradient(110deg,rgba(21,28,43,.95),rgba(17,22,35,.95))
}
.property-info{
min-width:0;
flex:1
}
.property-name{
font-size:16px;
font-weight:700;
color:#f4f5fb
}
.property-description{
margin-top:5px;
font-size:14px;
color:#9794bb;
line-height:1.3
}
.property-control{flex-shrink:0}
.property-input,.property-select{
width:240px;
max-width:100%;
margin:0;
background:#0b0f18;
border:1px solid #343d58
}
.empty{
grid-column:1/-1;
padding:20px;
color:#9299b8
}
.section-note{
color:#9299b8;
font-size:13px;
margin-top:8px
}
.save-msg{
margin-left:8px;
color:#a9a4c7
}
.switch{
position:relative;
display:inline-block;
width:68px;
height:38px
}
.switch input{
opacity:0;
width:0;
height:0;
position:absolute
}
.slider{
position:absolute;
inset:0;
cursor:pointer;
border-radius:999px;
background:#30364a;
border:1px solid #414962;
transition:.22s;
box-shadow:inset 0 0 0 1px rgba(255,255,255,.02)
}
.slider:before{
content:"";
position:absolute;
width:28px;
height:28px;
left:4px;
top:4px;
background:#f7f7fb;
border-radius:50%;
transition:.22s;
box-shadow:0 2px 7px rgba(0,0,0,.35)
}
.switch input:checked+.slider{
background:linear-gradient(135deg,#9333ea,#a855f7);
border-color:#a855f7;
box-shadow:0 0 18px rgba(168,85,247,.28)
}
.switch input:checked+.slider:before{
transform:translateX(30px)
}
.switch-state{
margin-top:4px;
text-align:center;
font-size:11px;
color:#9794bb;
font-weight:bold
}
@media(max-width:550px){
.property{align-items:flex-start}
.property-control{width:110px}
.property-input,.property-select{width:100%}
}
</style>
</head>

<body>
<div class="wrap">

<div class="top">
<div>
<div class="title">⚙️ Server Properties</div>
<div class="subtitle">Edita la configuración de tu servidor de forma fácil.</div>
</div>
<div id="status" class="status">● CARGANDO</div>
</div>

<div class="grid">

<div class="card">
<h3>Minecraft</h3>
<div id="minecraft" class="value">-</div>
</div>

<div class="card">
<h3>Plataforma</h3>
<div id="platform" class="value">-</div>
</div>

<div class="card">
<h3>RAM asignada</h3>
<div id="assigned" class="value">-</div>
</div>

<div class="card">
<h3>RAM del sistema</h3>
<div id="used" class="value">-</div>
<div class="bar">
<div id="fill" class="fill"></div>
</div>
<span id="avail" class="muted"></span>
</div>

</div>

<div class="card">

<div class="properties-header">

<div>
<h2 style="margin-bottom:0">⚙️ Server Properties</h2>
<div class="section-note">
Los ajustes booleanos aparecen como interruptores ON/OFF.
</div>
</div>

<div class="properties-actions">
<button class="primary" onclick="saveProps()">💾 Guardar cambios</button>
<button onclick="resetProps()">↩ Restablecer</button>
</div>

</div>

<div id="props" class="props"></div>
<span id="msg" class="save-msg"></span>

</div>

<div class="card">

<h2>👥 Jugadores</h2>

<div class="row">
<input id="player" maxlength="16" placeholder="Nombre del jugador">
<button onclick="act('whitelist-add')">Whitelist +</button>
<button onclick="act('whitelist-remove')">Whitelist −</button>
<button onclick="act('ban')">Banear</button>
<button onclick="act('unban')">Desbanear</button>
<button onclick="act('op')">Dar OP</button>
<button onclick="act('deop')">Quitar OP</button>
</div>

<div class="two">

<div>
<h3>Whitelist</h3>
<div id="wl">-</div>
</div>

<div>
<h3>Baneados</h3>
<div id="banned">-</div>

<h3>Operadores</h3>
<div id="ops">-</div>
</div>

</div>
</div>

<div class="card">

<div style="display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap;margin-bottom:15px">

<h2 style="margin:0">📡 Consola</h2>

<button class="stop-button" onclick="stopServer()">
🛑 STOP
</button>

</div>

<div id="console" class="console">-</div>

</div>

<div class="muted" id="updated"></div>

</div>

<script>

let data={};
let renderedPropertiesSignature='';

const PROPERTY_INFO={
'pvp':['PVP','Permite el combate entre jugadores'],
'hardcore':['Modo hardcore','Si mueres, no podrás reaparecer'],
'allow-flight':['Permitir vuelo','Permite a los jugadores volar'],
'online-mode':['Modo online','Verifica cuentas de Minecraft (recomendado)'],
'white-list':['Whitelist (lista blanca)','Solo los jugadores en la lista blanca pueden entrar'],
'spawn-animals':['Animales','Genera animales en el mundo'],
'spawn-monsters':['Monstruos','Genera monstruos en el mundo'],
'spawn-npcs':['Aldeanos','Genera aldeanos en el mundo'],
'do-daylight-cycle':['Ciclo de día y noche','Activa el paso del tiempo'],
'enable-command-block':['Bloques de comandos','Permite el uso de bloques de comandos'],
'generate-structures':['Generar estructuras','Genera aldeas, templos, etc.'],
'enforce-secure-profile':['Enforce Secure Profile','Requiere perfiles seguros (recomendado)'],
'allow-nether':['Permitir Nether','Permite el acceso al Nether'],
'allow-end':['Permitir The End','Permite el acceso al End'],
'spawn-protection':['Spawn protection','Protege el área de spawn'],
'villager-trading':['Comercio con aldeanos','Permite intercambiar con aldeanos'],
'entity-collision-enabled':['Colisiones de entidades','Activa las colisiones entre entidades'],
'enable-rcon':['RCON','Habilita el control remoto (RCON)'],
'enable-jmx-monitoring':['Monitoreo por JMX','Habilita JMX (útil para herramientas)'],
'enable-query':['Query','Habilita el protocolo de consulta del servidor'],
'enable-status':['Estado del servidor','Permite consultar el estado del servidor'],
'debug':['Modo debug','Activa información adicional de depuración'],
'force-gamemode':['Forzar gamemode','Obliga a los jugadores a usar el gamemode definido'],
'enforce-whitelist':['Forzar whitelist','Expulsa a jugadores que no estén en la whitelist'],
'accepts-transfers':['Aceptar transferencias','Permite transferencias del servidor'],
'broadcast-console-to-ops':['Consola para operadores','Envía mensajes de consola a los operadores'],
'broadcast-rcon-to-ops':['RCON para operadores','Envía mensajes RCON a los operadores']
};

const BOOLEAN_KEYS=new Set([
'pvp',
'hardcore',
'allow-flight',
'online-mode',
'white-list',
'spawn-animals',
'spawn-monsters',
'spawn-npcs',
'do-daylight-cycle',
'enable-command-block',
'generate-structures',
'enforce-secure-profile',
'allow-nether',
'allow-end',
'spawn-protection',
'villager-trading',
'entity-collision-enabled',
'enable-rcon',
'enable-jmx-monitoring',
'enable-query',
'enable-status',
'debug',
'force-gamemode',
'enforce-whitelist',
'accepts-transfers',
'broadcast-console-to-ops',
'broadcast-rcon-to-ops'
]);

const SELECT_OPTIONS={
'difficulty':[
['peaceful','Pacífico'],
['easy','Fácil'],
['normal','Normal'],
['hard','Difícil']
],
'gamemode':[
['survival','Supervivencia'],
['creative','Creativo'],
['adventure','Aventura'],
['spectator','Espectador']
],
'level-type':[
['minecraft:normal','Normal'],
['minecraft:flat','Plano'],
['minecraft:large_biomes','Biomas grandes'],
['minecraft:amplified','Amplificado']
]
};

const FRIENDLY_NAMES={
'server-port':'Puerto del servidor',
'server-ip':'IP del servidor',
'max-players':'Máx. jugadores',
'view-distance':'Distancia de renderizado',
'simulation-distance':'Distancia de simulación',
'motd':'Mensaje del servidor (MOTD)',
'level-name':'Nombre del mundo',
'level-seed':'Semilla del mundo',
'level-type':'Tipo de mundo',
'difficulty':'Dificultad',
'gamemode':'Gamemode',
'rcon.port':'Puerto RCON',
'rcon.password':'Contraseña RCON',
'resource-pack':'Paquete de recursos',
'max-world-size':'Tamaño máximo del mundo',
'max-tick-time':'Tiempo máximo de tick',
'rate-limit':'Límite de velocidad',
'network-compression-threshold':'Umbral de compresión',
'player-idle-timeout':'Tiempo de inactividad',
'op-permission-level':'Nivel de permisos OP',
'function-permission-level':'Nivel de permisos de funciones',
'entity-broadcast-range-percentage':'Rango de emisión de entidades'
};

const FRIENDLY_DESCRIPTIONS={
'max-players':'Cantidad máxima de jugadores',
'view-distance':'Chunks que pueden ver los jugadores',
'simulation-distance':'Chunks cargados y simulados',
'motd':'Mensaje que verán los jugadores',
'level-name':'Nombre de la carpeta del mundo',
'level-seed':'Semilla utilizada para generar el mundo',
'server-port':'Puerto utilizado por el servidor',
'server-ip':'IP en la que escucha el servidor',
'gamemode':'Modo de juego por defecto',
'difficulty':'Dificultad del mundo',
'level-type':'Tipo de generación del mundo',
'rcon.password':'Contraseña utilizada para RCON',
'rcon.port':'Puerto utilizado por RCON'
};

function esc(x){
return String(x).replace(/[&<>"']/g,m=>({
'&':'&amp;',
'<':'&lt;',
'>':'&gt;',
'"':'&quot;',
"'":'&#39;'
}[m]))
}

function propertyLabel(k){
return PROPERTY_INFO[k]
?PROPERTY_INFO[k][0]
:(FRIENDLY_NAMES[k]||k.split('-').map(
x=>x.charAt(0).toUpperCase()+x.slice(1)
).join(' '))
}

function propertyDescription(k){
return PROPERTY_INFO[k]
?PROPERTY_INFO[k][1]
:(FRIENDLY_DESCRIPTIONS[k]||'Configuración del servidor Minecraft')
}

function isBooleanProperty(k,v){
return BOOLEAN_KEYS.has(k)||
String(v).toLowerCase()==='true'||
String(v).toLowerCase()==='false'
}

function isNumericValue(v){
return /^-?\d+(\.\d+)?$/.test(String(v).trim())
}

function makeSwitch(k,v){
let checked=String(v).toLowerCase()==='true';

return '<label class="switch">'+
'<input type="checkbox" data-key="'+esc(k)+
'" data-type="boolean" '+(checked?'checked':'')+
' onchange="updateSwitchText(this)">'+
'<span class="slider"></span>'+
'</label>'+
'<div class="switch-state">'+
(checked?'ON':'OFF')+
'</div>'
}

function makeSelect(k,v){
let options=SELECT_OPTIONS[k];

if(!options)return null;

return '<select class="property-select" data-key="'+esc(k)+
'" data-type="select">'+
options.map(([x,label])=>
'<option value="'+esc(x)+'" '+
(String(v).toLowerCase()===x?'selected':'')+
'>'+esc(label)+'</option>'
).join('')+
'</select>'
}

function makeControl(k,v){

if(isBooleanProperty(k,v))
return makeSwitch(k,v);

let s=makeSelect(k,v);

if(s)return s;

let type=isNumericValue(v)?'number':'text';

return '<input class="property-input" type="'+type+
'" data-key="'+esc(k)+
'" data-type="'+type+
'" value="'+esc(v)+'">'
}

function propertySignature(p){
return JSON.stringify(p||{})
}

function renderProps(force=false){

let p=data.properties||{};
let el=document.getElementById('props');

if(!Object.keys(p).length){

el.innerHTML=
'<div class="empty">'+
'server.properties aún no existe. Inicia el servidor una vez.'+
'</div>';

renderedPropertiesSignature='';
return
}

let sig=propertySignature(p);

if(!force&&sig===renderedPropertiesSignature)
return;

renderedPropertiesSignature=sig;

el.innerHTML=Object.entries(p).map(
([k,v])=>
'<div class="property">'+
'<div class="property-info">'+
'<div class="property-name">'+
esc(propertyLabel(k))+
'</div>'+
'<div class="property-description">'+
esc(propertyDescription(k))+
'</div>'+
'</div>'+
'<div class="property-control">'+
makeControl(k,v)+
'</div>'+
'</div>'
).join('');

document.querySelectorAll('.switch input')
.forEach(updateSwitchText)
}

function updateSwitchText(input){

let state=
input.closest('.property-control')
?.querySelector('.switch-state');

if(state)
state.textContent=input.checked?'ON':'OFF'
}

async function refresh(){

try{

let r=await fetch('/api/status?_='+Date.now());
data=await r.json();

document.getElementById('minecraft').textContent=data.minecraft;
document.getElementById('platform').textContent=data.platform;

document.getElementById('assigned').textContent=
data.ram_assigned+' GB';

document.getElementById('used').textContent=
data.ram_used+' / '+data.ram_total+
' GB ('+data.ram_percent+'%)';

document.getElementById('fill').style.width=
data.ram_percent+'%';

document.getElementById('avail').textContent=
'Disponible: '+data.ram_available+' GB';

document.getElementById('console').textContent=
data.console||'Sin consola';

document.getElementById('wl').innerHTML=
(data.whitelist||[]).map(
x=>'<span class="tag">'+esc(x)+'</span>'
).join('')||
'<span class="muted">Vacía</span>';

document.getElementById('banned').innerHTML=
(data.banned||[]).map(
x=>'<span class="tag">'+esc(x)+'</span>'
).join('')||
'<span class="muted">Ninguno</span>';

document.getElementById('ops').innerHTML=
(data.ops||[]).map(
x=>'<span class="tag">'+esc(x)+'</span>'
).join('')||
'<span class="muted">Ninguno</span>';

let s=document.getElementById('status');

s.textContent=
data.online?'● ONLINE':'● OFFLINE';

s.style.color=
data.online?'#6dff9b':'#ff6b6b';

renderProps();

document.getElementById('updated').textContent=
'Actualizado: '+
new Date().toLocaleTimeString();

}catch(e){

document.getElementById('status').textContent=
'● SIN CONEXIÓN';

}
}

async function stopServer(){

if(!data.online){
alert('El servidor ya está apagado.');
return;
}

if(!confirm(
'¿Seguro que quieres apagar el servidor de Minecraft?'
))
return;

try{

let r=await fetch('/api/stop',{
method:'POST',
headers:{
'Content-Type':'application/json'
},
body:'{}'
});

let d=await r.json();

document.getElementById('msg').textContent=
d.message;

if(!d.ok){
alert(d.message);
}

setTimeout(refresh,1000);

}catch(e){

alert('No se pudo conectar con el dashboard');

}
}

async function act(a){

let n=document.getElementById('player').value.trim();

if(!n)
return alert('Escribe el nombre del jugador');

let r=await fetch('/api/player',{
method:'POST',
headers:{
'Content-Type':'application/json'
},
body:JSON.stringify({
action:a,
name:n
})
});

let d=await r.json();

document.getElementById('msg').textContent=
d.message;

setTimeout(refresh,700)
}

async function saveProps(){

let o={};

document.querySelectorAll('#props [data-key]')
.forEach(el=>{
o[el.dataset.key]=
el.dataset.type==='boolean'
?(el.checked?'true':'false')
:el.value
});

try{

let r=await fetch('/api/properties',{
method:'POST',
headers:{
'Content-Type':'application/json'
},
body:JSON.stringify(o)
});

let d=await r.json();

document.getElementById('msg').textContent=
d.message;

if(d.ok){

renderedPropertiesSignature='';

await refresh();

}

}catch(e){

document.getElementById('msg').textContent=
'No se pudieron guardar las propiedades.';

}
}

function resetProps(){

renderedPropertiesSignature='';

renderProps(true);

document.getElementById('msg').textContent=
'Cambios locales restablecidos.';
}

refresh();

setInterval(refresh,2000);

</script>

</body>
</html>'''

    with open(DASHBOARD_HTML,'w',encoding='utf-8') as f:
        f.write(html_doc)

class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self,*a,**kw):
        super().__init__(*a,directory=DASHBOARD_DIR,**kw)

    def _json(self,d,code=200):

        b=json.dumps(
            d,
            ensure_ascii=False
        ).encode()

        self.send_response(code)

        self.send_header(
            'Content-Type',
            'application/json; charset=utf-8'
        )

        self.send_header(
            'Cache-Control',
            'no-cache'
        )

        self.send_header(
            'Content-Length',
            str(len(b))
        )

        self.end_headers()

        self.wfile.write(b)

    def do_GET(self):

        if self.path.startswith('/api/status'):
            return self._json(dashboard_data())

        return super().do_GET()

    def do_POST(self):

        n=int(
            self.headers.get(
                'Content-Length',
                '0'
            )
        )

        raw=self.rfile.read(n)

        try:
            d=json.loads(raw or b'{}')

        except Exception:
            return self._json({
                'ok':False,
                'message':'JSON inválido'
            },400)

        if self.path=='/api/stop':

            ok,msg=detener_servidor()

            return self._json({
                'ok':ok,
                'message':msg
            },200 if ok else 400)

        if self.path=='/api/player':

            ok,msg=accion_jugador(
                str(d.get('action','')),
                str(d.get('name',''))
            )

            return self._json({
                'ok':ok,
                'message':msg
            },200 if ok else 400)

        if self.path=='/api/properties':

            if minecraft_process is not None and minecraft_process.poll() is None:

                return self._json({
                    'ok':False,
                    'message':
                    'Detén el servidor antes de cambiar server.properties'
                },409)

            changes={}

            for k,v in d.items():

                key=str(k)

                if re.fullmatch(
                    r'[A-Za-z0-9._-]{1,80}',
                    key
                ):

                    value=str(v)

                    if value.lower() in (
                        'true',
                        'false'
                    ):
                        value=value.lower()

                    changes[key]=value

            guardar_propiedades(changes)

            return self._json({
                'ok':True,
                'message':
                'Propiedades guardadas. Reinicia el servidor para aplicarlas.'
            })

        return self._json({
            'ok':False,
            'message':'Ruta no encontrada'
        },404)

    def log_message(self,*a):
        pass

class TCP(socketserver.TCPServer):
    allow_reuse_address=True

def iniciar_dashboard():

    global dashboard_server

    generar_dashboard()

    if dashboard_server:
        return

    try:

        dashboard_server=TCP(
            ('0.0.0.0',DASHBOARD_PORT),
            Handler
        )

        threading.Thread(
            target=dashboard_server.serve_forever,
            daemon=True
        ).start()

        print(
            f'{VERDE}🌐 Dashboard: puerto '
            f'{DASHBOARD_PORT}{RESET}'
        )

    except OSError as e:

        print(
            f'{AMARILLO}⚠️ Dashboard: '
            f'{e}{RESET}'
        )

def detener_dashboard():

    global dashboard_server

    if dashboard_server:

        try:
            dashboard_server.shutdown()
            dashboard_server.server_close()

        except Exception:
            pass

        dashboard_server=None

def instalar_java():

    if not comando_existe('java'):
        return False

    try:

        r=subprocess.run(
            ['java','-version'],
            capture_output=True,
            text=True
        )

        v=re.search(
            r'version "(\d+)',
            r.stderr+r.stdout
        )

        return bool(
            v and int(v.group(1))>=21
        )

    except Exception:
        return False

def obtener_manifest():

    try:

        q=urllib.request.Request(
            VERSION_MANIFEST,
            headers={'User-Agent':USER_AGENT}
        )

        return json.load(
            urllib.request.urlopen(
                q,
                timeout=30
            )
        )

    except Exception:
        return None

def obtener_info_version(v):

    m=obtener_manifest()

    if m:

        for x in m.get('versions',[]):

            if x.get('id')==v:
                return x

def descargar_archivo(url,dest):

    try:

        os.makedirs(
            os.path.dirname(dest),
            exist_ok=True
        )

        tmp=dest+'.downloading'

        q=urllib.request.Request(
            url,
            headers={'User-Agent':USER_AGENT}
        )

        with urllib.request.urlopen(
            q,
            timeout=180
        ) as r,open(tmp,'wb') as f:

            shutil.copyfileobj(r,f)

        if os.path.getsize(tmp)<=0:
            return False

        os.replace(tmp,dest)

        return True

    except Exception:
        return False

def aceptar_eula():

    os.makedirs(
        SERVER_DIR,
        exist_ok=True
    )

    open(
        EULA_FILE,
        'w'
    ).write(
        'eula=true\n'
    )

def descargar_vanilla(v):

    i=obtener_info_version(v)

    if not i:
        return False

    try:

        q=urllib.request.Request(
            i['url'],
            headers={'User-Agent':USER_AGENT}
        )

        d=json.load(
            urllib.request.urlopen(
                q,
                timeout=30
            )
        )

        u=d['downloads']['server']['url']

        if not descargar_archivo(
            u,
            SERVER_JAR
        ):
            return False

        guardar_json(
            SERVER_INFO_FILE,
            {
                'minecraft_version':v,
                'tipo':'Vanilla',
                'plataforma':None
            }
        )

        aceptar_eula()

        return True

    except Exception:
        return False

def servidor_corresponde(v,t,p):

    return (
        os.path.exists(SERVER_JAR)
        and server_info()==(v,t,p)
    )

def asegurar_servidor():

    v,t,p=server_info()

    if not v or not t:
        return False

    if not servidor_corresponde(v,t,p):
        return descargar_servidor(v,t,p)

    aceptar_eula()

    return True

def descargar_servidor(v,t,p):

    os.makedirs(
        SERVER_DIR,
        exist_ok=True
    )

    if os.path.exists(SERVER_JAR):

        try:
            os.remove(SERVER_JAR)

        except Exception:
            return False

    if t=='Vanilla':
        return descargar_vanilla(v)

    if t=='Plugins' and p=='Paper':

        try:

            u=(
                f'https://api.papermc.io/v2/projects/'
                f'paper/versions/{v}'
            )

            d=json.load(
                urllib.request.urlopen(
                    u,
                    timeout=30
                )
            )

            b=d['builds'][-1]

            jar=f'paper-{v}-{b}.jar'

            u=(
                f'https://api.papermc.io/v2/projects/'
                f'paper/versions/{v}/builds/{b}/downloads/{jar}'
            )

            ok=descargar_archivo(
                u,
                SERVER_JAR
            )

            if ok:

                guardar_json(
                    SERVER_INFO_FILE,
                    {
                        'minecraft_version':v,
                        'tipo':t,
                        'plataforma':p,
                        'software_version':b
                    }
                )

                aceptar_eula()

            return ok

        except Exception:
            return False

    return False

def seleccionar_version():

    while True:

        v=input(
            'Versión de Minecraft: '
        ).strip()

        if obtener_info_version(v):
            return v

        print('❌ Versión no encontrada')

def seleccionar_tipo():

    while True:

        print(
            '1. Vanilla\n'
            '2. Plugins (Paper)'
        )

        x=input(
            'Opción: '
        ).strip()

        if x=='1':
            return 'Vanilla',None

        if x=='2':
            return 'Plugins','Paper'

def configurar_servidor():

    limpiar()

    v=seleccionar_version()
    t,p=seleccionar_tipo()

    guardar_configuracion(
        v,
        t,
        p
    )

    if descargar_servidor(v,t,p):

        print(
            f'{VERDE}✅ Servidor preparado{RESET}'
        )

    else:

        print(
            f'{ROJO}❌ No se pudo preparar{RESET}'
        )

    pausa()

def configurar_ram():

    limpiar()

    print(
        'RAM actual:',
        obtener_ram(),
        'GB'
    )

    x=input(
        'Nueva RAM GB: '
    ).strip()

    try:

        r=int(x)

        if r>=1:

            guardar_ram(r)

            print(
                '✅ RAM guardada'
            )

    except Exception:

        print(
            '❌ Valor inválido'
        )

    pausa()

def lanzar_servidor():

    global minecraft_process

    v,t,p=server_info()

    if not v or not asegurar_servidor():

        print(
            '❌ Servidor no configurado'
        )

        pausa()
        return

    if not instalar_java():

        print(
            '❌ Java 21+ requerido'
        )

        pausa()
        return

    aceptar_eula()

    s=cargar_estado()
    s['console']=[]
    guardar_estado(s)

    iniciar_dashboard()

    cmd=[
        'java',
        f'-Xmx{obtener_ram()}G',
        '-jar',
        'server.jar',
        '--nogui'
    ]

    print(
        f'{VERDE}🚀 Iniciando servidor...{RESET}'
    )

    try:

        minecraft_process=subprocess.Popen(
            cmd,
            cwd=SERVER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        for line in minecraft_process.stdout:

            print(
                line,
                end='',
                flush=True
            )

            guardar_linea_consola(line)

            ip=extraer_ip_playit(line)

            if ip:
                guardar_ip_playit(ip)

        minecraft_process.wait()

    except KeyboardInterrupt:

        if minecraft_process:

            try:
                minecraft_process.terminate()

            except Exception:
                pass

    finally:

        minecraft_process=None

    pausa()

def borrar_servidor():

    limpiar()

    x=input(
        'Escribe BORRAR SERVIDOR para confirmar: '
    )

    if x=='BORRAR SERVIDOR':

        if os.path.exists(SERVER_DIR):
            shutil.rmtree(SERVER_DIR)

        s=cargar_estado()

        for k in [
            'minecraft',
            'launch',
            'playit',
            'console'
        ]:
            s.pop(k,None)

        guardar_estado(s)

        print(
            '✅ Eliminado'
        )

    pausa()

def interfaz():

    while True:

        v,t,p=server_info()

        limpiar()

        print(
f'''
╔══════════════════════════════════════════════╗
║          🟩 MINECRAFT SERVER                ║
╠══════════════════════════════════════════════╣
║ Minecraft:  {str(v or "No configurado"):<30}║
║ Tipo:       {str(t or "No configurado"):<30}║
║ Plataforma: {str(p or "Vanilla"):<30}║
║ RAM:        {str(obtener_ram())+" GB":<30}║
╠══════════════════════════════════════════════╣
║ 1. 🚀 Lanzar servidor                       ║
║ 2. ⚙️  Configurar servidor                  ║
║ 3. 💾 Configurar RAM                        ║
║ 4. 🗑️  Borrar servidor                      ║
║ 5. ❌ Salir                                 ║
╚══════════════════════════════════════════════╝
'''
        )

        x=input(
            'Opción: '
        ).strip()

        if x=='1':
            lanzar_servidor()

        elif x=='2':
            configurar_servidor()

        elif x=='3':
            configurar_ram()

        elif x=='4':
            borrar_servidor()

        elif x=='5':
            return

def main():

    os.makedirs(
        BASE_DIR,
        exist_ok=True
    )

    if not cargar_estado().get('minecraft'):
        configurar_servidor()

    interfaz()

if __name__=='__main__':
    main()
