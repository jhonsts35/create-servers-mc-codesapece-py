#!/usr/bin/env python3

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import threading
import http.server
import socketserver


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ESTADO_FILE = os.path.join(BASE_DIR, ".setup_state.json")
SERVER_DIR = os.path.join(BASE_DIR, "minecraft-server")
SERVER_JAR = os.path.join(SERVER_DIR, "server.jar")
SERVER_INFO_FILE = os.path.join(SERVER_DIR, ".server_info.json")
EULA_FILE = os.path.join(SERVER_DIR, "eula.txt")
PLUGINS_DIR = os.path.join(SERVER_DIR, "plugins")

DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")
DASHBOARD_FILE = os.path.join(DASHBOARD_DIR, "index.html")
DASHBOARD_PORT = 8080

USER_AGENT = "MinecraftServerSetup/4.0"

VERSION_MANIFEST = (
    "https://piston-meta.mojang.com/"
    "mc/game/version_manifest_v2.json"
)

PLAYIT_PLUGIN_URL = (
    "https://github.com/playit-cloud/playit-minecraft-plugin/"
    "releases/latest/download/playit-minecraft-plugin.jar"
)

PLAYIT_PLUGIN_FILE = os.path.join(
    PLUGINS_DIR,
    "playit-minecraft-plugin.jar"
)

VERDE = "\033[92m"
AMARILLO = "\033[93m"
ROJO = "\033[91m"
CIAN = "\033[96m"
MAGENTA = "\033[95m"
RESET = "\033[0m"


# ============================================================
# ESTADO EN MEMORIA DEL PROCESO DE MINECRAFT / DASHBOARD
# (Esto es lo que se injertó desde la versión que sí funciona)
# ============================================================

minecraft_process = None
minecraft_lock = threading.Lock()
dashboard_server = None
CONSOLA_BUFFER = ""


# ============================================================
# UTILIDADES
# ============================================================

def limpiar():
    os.system("clear")


def pausa():
    input("\nPresiona ENTER para continuar...")


def comando_existe(comando):
    return shutil.which(comando) is not None


def cargar_json(ruta):
    if not os.path.exists(ruta):
        return {}

    try:
        with open(ruta, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    except Exception:
        return {}


def guardar_json(ruta, datos):
    directorio = os.path.dirname(ruta)

    if directorio:
        os.makedirs(directorio, exist_ok=True)

    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=4, ensure_ascii=False)


def cargar_estado():
    return cargar_json(ESTADO_FILE)


def guardar_estado(estado):
    guardar_json(ESTADO_FILE, estado)


def cargar_server_info():
    return cargar_json(SERVER_INFO_FILE)


def guardar_server_info(
    version,
    tipo,
    plataforma,
    software_version=None
):
    os.makedirs(SERVER_DIR, exist_ok=True)

    guardar_json(
        SERVER_INFO_FILE,
        {
            "minecraft_version": version,
            "tipo": tipo,
            "plataforma": plataforma,
            "software_version": software_version
        }
    )


# ============================================================
# DASHBOARD (INJERTADO: ahora se sirve con un servidor HTTP real
# en vez de depender de que algo externo lea status.json)
# ============================================================

def generar_dashboard():
    os.makedirs(DASHBOARD_DIR, exist_ok=True)

    html = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minecraft Server Dashboard</title>

<style>
*{
    box-sizing:border-box;
}

body{
    margin:0;
    min-height:100vh;
    background:
        radial-gradient(circle at top right,#24114f 0,#101525 28%,#0b0f18 65%);
    color:#f5f7ff;
    font-family:Inter,Segoe UI,Arial,sans-serif;
}

.container{
    width:min(1200px,94%);
    margin:40px auto;
}

.header{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
    margin-bottom:28px;
}

.title{
    font-size:32px;
    font-weight:800;
}

.subtitle{
    color:#8e96aa;
    margin-top:6px;
}

.status{
    display:flex;
    align-items:center;
    gap:9px;
    padding:10px 16px;
    border-radius:999px;
    background:#151b2b;
    border:1px solid #252d43;
}

.dot{
    width:10px;
    height:10px;
    border-radius:50%;
    background:#777;
}

.online .dot{
    background:#35e58a;
    box-shadow:0 0 15px #35e58a;
}

.offline .dot{
    background:#ff5364;
}

.grid{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    gap:16px;
}

.card{
    background:rgba(18,23,37,.88);
    border:1px solid #252d43;
    border-radius:18px;
    padding:22px;
    box-shadow:0 15px 50px rgba(0,0,0,.25);
}

.label{
    color:#858da2;
    font-size:13px;
    text-transform:uppercase;
    letter-spacing:.08em;
}

.value{
    margin-top:9px;
    font-size:24px;
    font-weight:750;
}

.main{
    margin-top:18px;
    display:grid;
    grid-template-columns:1.6fr 1fr;
    gap:18px;
}

.console{
    height:480px;
    overflow:auto;
    background:#070a11;
    border-radius:14px;
    padding:18px;
    color:#cfd7e7;
    font-family:Consolas,monospace;
    font-size:13px;
    white-space:pre-wrap;
    border:1px solid #202638;
    user-select:text;
}

.console a{
    color:#7dd3fc;
    text-decoration:underline;
}

.console-tools{
    display:flex;
    gap:8px;
    margin-top:12px;
    flex-wrap:wrap;
}

.console-tools input{
    flex:1;
    min-width:160px;
    background:#0b0f18;
    color:#f5f7ff;
    border:1px solid #303951;
    border-radius:9px;
    padding:10px;
    font-family:Consolas,monospace;
}

.actions{
    display:grid;
    gap:12px;
}

button{
    width:100%;
    padding:15px;
    border-radius:12px;
    border:1px solid #303951;
    background:#171d2d;
    color:white;
    cursor:pointer;
    font-size:15px;
    font-weight:650;
}

button:hover{
    background:#20283d;
}

button.danger{
    border-color:#6d2734;
    background:#29151b;
}

.info{
    display:grid;
    gap:14px;
}

.info-row{
    display:flex;
    justify-content:space-between;
    gap:20px;
    padding:14px 0;
    border-bottom:1px solid #252d43;
}

.info-row:last-child{
    border-bottom:0;
}

.info-key{
    color:#8e96aa;
}

.info-value{
    font-weight:650;
    text-align:right;
}

.ip{
    color:#b995ff;
    word-break:break-all;
}

.toast{
    margin-top:10px;
    font-size:13px;
    color:#9aa4bd;
    min-height:16px;
}

.section{
    margin-top:18px;
}

.section-header{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:20px;
    margin-bottom:18px;
    flex-wrap:wrap;
}

.section-title{
    font-size:20px;
    font-weight:700;
}

.section-note{
    color:#8e96aa;
    font-size:13px;
    margin-top:6px;
}

.section-actions{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
}

.btn-sm{
    width:auto;
    padding:10px 16px;
    font-size:13px;
}

.props{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:8px 20px;
}

@media(max-width:900px){
    .props{
        grid-template-columns:1fr;
    }
}

.property{
    min-height:64px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:18px;
    padding:13px 18px;
    border:1px solid #252d43;
    border-radius:14px;
    background:linear-gradient(110deg,rgba(21,28,43,.95),rgba(17,22,35,.95));
}

.property-info{
    min-width:0;
    flex:1;
}

.property-name{
    font-size:15px;
    font-weight:700;
    color:#f4f5fb;
}

.property-description{
    margin-top:4px;
    font-size:13px;
    color:#8e96aa;
    line-height:1.3;
}

.property-control{
    flex-shrink:0;
}

.property-input,.property-select{
    width:220px;
    max-width:100%;
    margin:0;
    background:#0b0f18;
    border:1px solid #303951;
    border-radius:9px;
    padding:9px;
    color:#f5f7ff;
}

.empty-props{
    grid-column:1/-1;
    padding:20px;
    color:#8e96aa;
}

.switch{
    position:relative;
    display:inline-block;
    width:60px;
    height:34px;
}

.switch input{
    opacity:0;
    width:0;
    height:0;
    position:absolute;
}

.slider{
    position:absolute;
    inset:0;
    cursor:pointer;
    border-radius:999px;
    background:#30364a;
    border:1px solid #414962;
    transition:.22s;
}

.slider:before{
    content:"";
    position:absolute;
    width:24px;
    height:24px;
    left:4px;
    top:4px;
    background:#f7f7fb;
    border-radius:50%;
    transition:.22s;
}

.switch input:checked+.slider{
    background:linear-gradient(135deg,#9333ea,#a855f7);
    border-color:#a855f7;
}

.switch input:checked+.slider:before{
    transform:translateX(26px);
}

.switch-state{
    margin-top:4px;
    text-align:center;
    font-size:10px;
    color:#8e96aa;
    font-weight:bold;
}

.player-row{
    display:flex;
    flex-wrap:wrap;
    gap:8px;
    align-items:center;
}

.player-row input{
    background:#0b0f18;
    color:#f5f7ff;
    border:1px solid #303951;
    border-radius:9px;
    padding:10px;
    flex:1;
    min-width:160px;
}

.players-lists{
    display:grid;
    grid-template-columns:repeat(3,1fr);
    gap:16px;
    margin-top:18px;
}

@media(max-width:750px){
    .players-lists{
        grid-template-columns:1fr;
    }
}

.tag{
    display:inline-block;
    background:#171d2d;
    border:1px solid #303951;
    border-radius:15px;
    padding:5px 10px;
    margin:3px 4px 0 0;
    font-size:13px;
}

.muted{
    color:#8e96aa;
}

@media(max-width:900px){
    .grid{
        grid-template-columns:repeat(2,1fr);
    }

    .main{
        grid-template-columns:1fr;
    }
}

@media(max-width:550px){
    .grid{
        grid-template-columns:1fr;
    }

    .header{
        flex-direction:column;
        align-items:flex-start;
    }
}
</style>
</head>

<body>

<div class="container">

    <div class="header">
        <div>
            <div class="title">Minecraft Server</div>
            <div class="subtitle">Dashboard del servidor</div>
        </div>

        <div id="status" class="status offline">
            <span class="dot"></span>
            <span id="statusText">Offline</span>
        </div>
    </div>

    <div class="grid">

        <div class="card">
            <div class="label">Minecraft</div>
            <div class="value" id="version">-</div>
        </div>

        <div class="card">
            <div class="label">Tipo</div>
            <div class="value" id="tipo">-</div>
        </div>

        <div class="card">
            <div class="label">Plataforma</div>
            <div class="value" id="plataforma">-</div>
        </div>

        <div class="card">
            <div class="label">RAM</div>
            <div class="value" id="ram">-</div>
        </div>

    </div>

    <div class="main">

        <div class="card">
            <div class="label" style="margin-bottom:12px">
                Consola
            </div>

            <div id="console" class="console">
Esperando datos del servidor...
            </div>

            <div class="console-tools">
                <input id="comandoConsola"
                    placeholder="Escribe o pega un comando y presiona Enter"
                    onkeydown="if(event.key==='Enter') enviarComandoConsola()">

                <button class="btn-sm" onclick="enviarComandoConsola()">
                    ➤ Enviar
                </button>

                <button class="btn-sm" onclick="copiarConsola()">
                    📋 Copiar consola
                </button>
            </div>

            <div id="consolaMsg" class="toast"></div>
        </div>

        <div class="card">

            <div class="label">Información</div>

            <div class="info">

                <div class="info-row">
                    <div class="info-key">Estado</div>
                    <div class="info-value" id="infoStatus">
                        Offline
                    </div>
                </div>

                <div class="info-row">
                    <div class="info-key">IP Playit</div>
                    <div class="info-value ip" id="ip">
                        No disponible
                    </div>
                </div>

                <div class="info-row">
                    <div class="info-key">Última actualización</div>
                    <div class="info-value" id="updated">
                        -
                    </div>
                </div>

            </div>

            <div style="height:20px"></div>

            <div class="actions">
                <button onclick="accion('start')">
                    🚀 Iniciar servidor
                </button>

                <button class="danger" onclick="accion('stop')">
                    ⛔ Detener servidor
                </button>

                <button onclick="accion('restart')">
                    🔄 Reiniciar servidor
                </button>

                <button onclick="location.reload()">
                    ↻ Actualizar
                </button>
            </div>

            <div id="toast" class="toast"></div>

        </div>

    </div>

    <div class="section card">

        <div class="section-header">
            <div>
                <div class="section-title">⚙️ Server Properties</div>
                <div class="section-note">
                    Los ajustes true/false se muestran como switches.
                    Reinicia el servidor para aplicar los cambios.
                </div>
            </div>

            <div class="section-actions">
                <button class="btn-sm primary" onclick="guardarProps()">
                    💾 Guardar cambios
                </button>

                <button class="btn-sm" onclick="restablecerProps()">
                    ↩ Restablecer
                </button>
            </div>
        </div>

        <div id="props" class="props"></div>

        <div id="propsMsg" class="toast"></div>

    </div>

    <div class="section card">

        <div class="section-title" style="margin-bottom:14px">
            👥 Jugadores
        </div>

        <div class="player-row">
            <input id="jugador" maxlength="16"
                placeholder="Nombre exacto del jugador">

            <button class="btn-sm" onclick="accionJugador('whitelist-add')">
                Whitelist +
            </button>

            <button class="btn-sm" onclick="accionJugador('whitelist-remove')">
                Whitelist −
            </button>

            <button class="btn-sm danger" onclick="accionJugador('ban')">
                Banear
            </button>

            <button class="btn-sm" onclick="accionJugador('unban')">
                Desbanear
            </button>

            <button class="btn-sm" onclick="accionJugador('op')">
                Dar OP
            </button>

            <button class="btn-sm" onclick="accionJugador('deop')">
                Quitar OP
            </button>
        </div>

        <div id="jugadorMsg" class="toast"></div>

        <div class="players-lists">

            <div>
                <div class="label" style="margin-bottom:8px">
                    Whitelist
                </div>
                <div id="listaWhitelist">-</div>
            </div>

            <div>
                <div class="label" style="margin-bottom:8px">
                    Baneados
                </div>
                <div id="listaBaneados">-</div>
            </div>

            <div>
                <div class="label" style="margin-bottom:8px">
                    Operadores
                </div>
                <div id="listaOps">-</div>
            </div>

        </div>

    </div>

</div>

<script>
let ultimoEstado = {};
let firmaPropsRenderizada = "";

const PROPERTY_INFO = {
    "pvp": ["PVP", "Permite el combate entre jugadores"],
    "hardcore": ["Modo hardcore", "Si mueres, no podrás reaparecer"],
    "allow-flight": ["Permitir vuelo", "Permite a los jugadores volar"],
    "online-mode": ["Modo online", "Verifica cuentas de Minecraft (recomendado)"],
    "white-list": ["Whitelist (lista blanca)", "Solo los jugadores en la lista blanca pueden entrar"],
    "spawn-animals": ["Animales", "Genera animales en el mundo"],
    "spawn-monsters": ["Monstruos", "Genera monstruos en el mundo"],
    "spawn-npcs": ["Aldeanos", "Genera aldeanos en el mundo"],
    "do-daylight-cycle": ["Ciclo de día y noche", "Activa el paso del tiempo"],
    "enable-command-block": ["Bloques de comandos", "Permite el uso de bloques de comandos"],
    "generate-structures": ["Generar estructuras", "Genera aldeas, templos, etc."],
    "enforce-secure-profile": ["Enforce Secure Profile", "Requiere perfiles seguros (recomendado)"],
    "allow-nether": ["Permitir Nether", "Permite el acceso al Nether"],
    "allow-end": ["Permitir The End", "Permite el acceso al End"],
    "spawn-protection": ["Spawn protection", "Protege el área de spawn"],
    "enable-rcon": ["RCON", "Habilita el control remoto (RCON)"],
    "enable-query": ["Query", "Habilita el protocolo de consulta del servidor"],
    "enable-status": ["Estado del servidor", "Permite consultar el estado del servidor"],
    "debug": ["Modo debug", "Activa información adicional de depuración"],
    "force-gamemode": ["Forzar gamemode", "Obliga a los jugadores a usar el gamemode definido"],
    "enforce-whitelist": ["Forzar whitelist", "Expulsa a jugadores que no estén en la whitelist"]
};

const BOOLEAN_KEYS = new Set([
    "pvp","hardcore","allow-flight","online-mode","white-list",
    "spawn-animals","spawn-monsters","spawn-npcs","do-daylight-cycle",
    "enable-command-block","generate-structures","enforce-secure-profile",
    "allow-nether","allow-end","enable-rcon","enable-query","enable-status",
    "debug","force-gamemode","enforce-whitelist"
]);

const SELECT_OPTIONS = {
    "difficulty": [["peaceful","Pacífico"],["easy","Fácil"],["normal","Normal"],["hard","Difícil"]],
    "gamemode": [["survival","Supervivencia"],["creative","Creativo"],["adventure","Aventura"],["spectator","Espectador"]],
    "level-type": [["minecraft:normal","Normal"],["minecraft:flat","Plano"],["minecraft:large_biomes","Biomas grandes"],["minecraft:amplified","Amplificado"]]
};

const FRIENDLY_NAMES = {
    "server-port":"Puerto del servidor","server-ip":"IP del servidor",
    "max-players":"Máx. jugadores","view-distance":"Distancia de renderizado",
    "simulation-distance":"Distancia de simulación","motd":"Mensaje del servidor (MOTD)",
    "level-name":"Nombre del mundo","level-seed":"Semilla del mundo",
    "level-type":"Tipo de mundo","difficulty":"Dificultad","gamemode":"Gamemode",
    "rcon.port":"Puerto RCON","rcon.password":"Contraseña RCON"
};

const FRIENDLY_DESC = {
    "max-players":"Cantidad máxima de jugadores",
    "view-distance":"Chunks que pueden ver los jugadores",
    "motd":"Mensaje que verán los jugadores",
    "level-seed":"Semilla utilizada para generar el mundo",
    "gamemode":"Modo de juego por defecto",
    "difficulty":"Dificultad del mundo"
};

function esc(x){
    return String(x).replace(/[&<>"']/g, m => ({
        "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
    }[m]));
}

function enlazar(texto){
    const escapado = esc(texto);
    return escapado.replace(
        /(https?:\/\/[^\s<]+)/g,
        url => '<a href="'+url+'" target="_blank" rel="noopener noreferrer">'+url+'</a>'
    );
}

async function enviarComandoConsola(){
    const input = document.getElementById("comandoConsola");
    const cmd = input.value.trim();
    const msg = document.getElementById("consolaMsg");

    if(!cmd){
        return;
    }

    msg.textContent = "Enviando...";

    try{
        const respuesta = await fetch("/api/console",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify({command: cmd})
        });

        const data = await respuesta.json();
        msg.textContent = data.message || "";

        if(data.ok){
            input.value = "";
        }

    }catch(e){
        msg.textContent = "No se pudo enviar el comando.";
    }

    setTimeout(cargar,400);
}

async function copiarConsola(){
    const msg = document.getElementById("consolaMsg");
    const texto = (ultimoEstado.console || "");

    try{
        await navigator.clipboard.writeText(texto);
        msg.textContent = "Consola copiada al portapapeles.";
    }catch(e){
        msg.textContent = "No se pudo copiar (permiso del navegador).";
    }
}

function propertyLabel(k){
    return PROPERTY_INFO[k] ? PROPERTY_INFO[k][0]
        : (FRIENDLY_NAMES[k] || k.split("-").map(
            x => x.charAt(0).toUpperCase()+x.slice(1)
          ).join(" "));
}

function propertyDescription(k){
    return PROPERTY_INFO[k] ? PROPERTY_INFO[k][1]
        : (FRIENDLY_DESC[k] || "Configuración del servidor Minecraft");
}

function esBooleana(k,v){
    return BOOLEAN_KEYS.has(k)
        || String(v).toLowerCase()==="true"
        || String(v).toLowerCase()==="false";
}

function esNumerica(v){
    return /^-?\d+(\.\d+)?$/.test(String(v).trim());
}

function actualizarTextoSwitch(input){
    const estado = input.closest(".property-control")
        ?.querySelector(".switch-state");
    if(estado){
        estado.textContent = input.checked ? "ON" : "OFF";
    }
}

function crearSwitch(k,v){
    const checked = String(v).toLowerCase()==="true";
    return '<label class="switch">'+
        '<input type="checkbox" data-key="'+esc(k)+'" data-type="boolean" '+
        (checked?"checked":"")+
        ' onchange="actualizarTextoSwitch(this)">'+
        '<span class="slider"></span></label>'+
        '<div class="switch-state">'+(checked?"ON":"OFF")+'</div>';
}

function crearSelect(k,v){
    const options = SELECT_OPTIONS[k];
    if(!options) return null;
    return '<select class="property-select" data-key="'+esc(k)+'" data-type="select">'+
        options.map(([x,label]) =>
            '<option value="'+esc(x)+'" '+
            (String(v).toLowerCase()===x?"selected":"")+
            '>'+esc(label)+'</option>'
        ).join("")+
        '</select>';
}

function crearControl(k,v){
    if(esBooleana(k,v)) return crearSwitch(k,v);
    const sel = crearSelect(k,v);
    if(sel) return sel;
    const tipo = esNumerica(v) ? "number" : "text";
    return '<input class="property-input" type="'+tipo+'" '+
        'data-key="'+esc(k)+'" data-type="'+tipo+'" value="'+esc(v)+'">';
}

function renderizarProps(forzar){
    const props = ultimoEstado.properties || {};
    const contenedor = document.getElementById("props");

    if(!Object.keys(props).length){
        contenedor.innerHTML =
            '<div class="empty-props">server.properties aún no existe. '+
            'Inicia el servidor una vez para generarlo.</div>';
        firmaPropsRenderizada = "";
        return;
    }

    const firma = JSON.stringify(props);

    if(!forzar && firma===firmaPropsRenderizada){
        return;
    }

    firmaPropsRenderizada = firma;

    contenedor.innerHTML = Object.entries(props).map(([k,v]) =>
        '<div class="property">'+
        '<div class="property-info">'+
        '<div class="property-name">'+esc(propertyLabel(k))+'</div>'+
        '<div class="property-description">'+esc(propertyDescription(k))+'</div>'+
        '</div>'+
        '<div class="property-control">'+crearControl(k,v)+'</div>'+
        '</div>'
    ).join("");

    document.querySelectorAll("#props .switch input")
        .forEach(actualizarTextoSwitch);
}

async function guardarProps(){
    const cambios = {};

    document.querySelectorAll("#props [data-key]").forEach(el => {
        cambios[el.dataset.key] =
            el.dataset.type==="boolean" ? (el.checked?"true":"false") : el.value;
    });

    const msg = document.getElementById("propsMsg");
    msg.textContent = "Guardando...";

    try{
        const respuesta = await fetch("/api/properties",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify(cambios)
        });

        const data = await respuesta.json();
        msg.textContent = data.message || "";

        if(data.ok){
            firmaPropsRenderizada = "";
            await cargar();
        }

    }catch(e){
        msg.textContent = "No se pudieron guardar las propiedades.";
    }
}

function restablecerProps(){
    firmaPropsRenderizada = "";
    renderizarProps(true);
    document.getElementById("propsMsg").textContent =
        "Cambios locales restablecidos.";
}

async function accionJugador(accion){
    const nombre = document.getElementById("jugador").value.trim();
    const msg = document.getElementById("jugadorMsg");

    if(!nombre){
        msg.textContent = "Escribe el nombre del jugador.";
        return;
    }

    msg.textContent = "Enviando...";

    try{
        const respuesta = await fetch("/api/player",{
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body: JSON.stringify({action:accion, name:nombre})
        });

        const data = await respuesta.json();
        msg.textContent = data.message || "";

    }catch(e){
        msg.textContent = "No se pudo contactar al servidor.";
    }

    setTimeout(cargar,700);
}

function listaComoTags(lista){
    if(!lista || !lista.length){
        return '<span class="muted">Vacío</span>';
    }
    return lista.map(x => '<span class="tag">'+esc(x)+'</span>').join("");
}

async function cargar(){

    try{

        const respuesta = await fetch("/api/status?"+Date.now());

        if(!respuesta.ok){
            throw new Error();
        }

        const data = await respuesta.json();
        ultimoEstado = data;

        document.getElementById("version").textContent =
            data.minecraft_version || "-";

        document.getElementById("tipo").textContent =
            data.tipo || "-";

        document.getElementById("plataforma").textContent =
            data.plataforma || "Vanilla";

        document.getElementById("ram").textContent =
            data.ram ? data.ram + " GB" : "-";

        document.getElementById("ip").textContent =
            data.ip || "No disponible";

        document.getElementById("updated").textContent =
            data.updated || "-";

        const status =
            document.getElementById("status");

        const infoStatus =
            document.getElementById("infoStatus");

        const text =
            document.getElementById("statusText");

        if(data.online){

            status.className="status online";
            text.textContent="Online";
            infoStatus.textContent="Online";

        }else{

            status.className="status offline";
            text.textContent="Offline";
            infoStatus.textContent="Offline";
        }

        const consola = document.getElementById("console");
        const alFinal =
            consola.scrollTop + consola.clientHeight >=
            consola.scrollHeight - 30;

        consola.innerHTML = enlazar(data.console || "Sin registros.");

        if(alFinal){
            consola.scrollTop = consola.scrollHeight;
        }

        document.getElementById("listaWhitelist").innerHTML =
            listaComoTags(data.whitelist);

        document.getElementById("listaBaneados").innerHTML =
            listaComoTags(data.banned);

        document.getElementById("listaOps").innerHTML =
            listaComoTags(data.ops);

        renderizarProps(false);

    }catch(e){

        document.getElementById("status").className =
            "status offline";

        document.getElementById("statusText").textContent =
            "Sin conexión";

        document.getElementById("infoStatus").textContent =
            "Sin conexión";
    }
}

async function accion(tipo){

    const toast = document.getElementById("toast");
    toast.textContent = "Enviando...";

    try{

        const respuesta = await fetch(
            "/api/" + encodeURIComponent(tipo),
            { method: "POST" }
        );

        const data = await respuesta.json();

        toast.textContent = data.message || "";

    }catch(e){
        toast.textContent = "No se pudo contactar al servidor.";
    }

    cargar();
}

cargar();

setInterval(cargar,2000);
</script>

</body>
</html>
"""

    with open(
        DASHBOARD_FILE,
        "w",
        encoding="utf-8"
    ) as archivo:
        archivo.write(html)


def _procesar_linea_consola(linea):
    """Guarda cada línea de salida de Minecraft en el buffer en memoria
    que usa el dashboard, y detecta la IP de Playit si aparece."""

    global CONSOLA_BUFFER

    CONSOLA_BUFFER += linea

    if len(CONSOLA_BUFFER) > 30000:
        CONSOLA_BUFFER = CONSOLA_BUFFER[-30000:]

    ip = extraer_ip_playit(linea)

    if ip:
        guardar_ip_playit(ip)


def propiedades():
    """Lee minecraft-server/server.properties como diccionario."""

    ruta = os.path.join(SERVER_DIR, "server.properties")
    datos = {}

    if os.path.exists(ruta):

        try:
            with open(ruta, encoding="utf-8", errors="ignore") as archivo:

                for linea in archivo:

                    linea = linea.strip()

                    if linea and not linea.startswith("#") and "=" in linea:

                        clave, valor = linea.split("=", 1)
                        datos[clave.strip()] = valor.strip()

        except Exception:
            pass

    return datos


def guardar_propiedades(cambios):
    """Reescribe server.properties aplicando los cambios recibidos,
    preservando las líneas que no cambiaron."""

    os.makedirs(SERVER_DIR, exist_ok=True)

    ruta = os.path.join(SERVER_DIR, "server.properties")
    anteriores = []
    vistas = set()

    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8", errors="ignore") as archivo:
            anteriores = archivo.read().splitlines()

    salida = []

    for linea in anteriores:

        if "=" in linea and not linea.lstrip().startswith("#"):

            clave = linea.split("=", 1)[0].strip()

            if clave in cambios:
                salida.append(clave + "=" + str(cambios[clave]))
                vistas.add(clave)
                continue

        salida.append(linea)

    for clave, valor in cambios.items():

        if clave not in vistas:
            salida.append(clave + "=" + str(valor))

    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(salida) + "\n")


def lista_archivo(nombre):
    """Lee un JSON de minecraft-server/ como whitelist.json, ops.json,
    banned-players.json, etc."""

    try:

        ruta = os.path.join(SERVER_DIR, nombre)

        if not os.path.exists(ruta):
            return []

        with open(ruta, encoding="utf-8") as archivo:
            return json.load(archivo)

    except Exception:
        return []


def nombres_archivo(nombre):

    return [
        entrada.get("name", entrada.get("uuid", ""))
        for entrada in lista_archivo(nombre)
    ]


def accion_jugador(accion, nombre):
    """Ejecuta acciones de whitelist/ban/op mandando el comando de
    consola correspondiente al proceso de Minecraft."""

    nombre = nombre.strip()

    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", nombre):
        return False, "Nombre de jugador inválido."

    comandos = {
        "whitelist-add": f"whitelist add {nombre}",
        "whitelist-remove": f"whitelist remove {nombre}",
        "ban": f"ban {nombre}",
        "unban": f"pardon {nombre}",
        "op": f"op {nombre}",
        "deop": f"deop {nombre}"
    }

    if accion not in comandos:
        return False, "Acción no reconocida."

    if enviar_comando(comandos[accion]):
        return True, "Comando enviado al servidor."

    return False, "El servidor está apagado. Enciéndelo primero."


def dashboard_data():
    """Estado actual, calculado al vuelo (no depende de un archivo
    status.json que nadie sirve)."""

    version, tipo, plataforma, ram = obtener_configuracion()

    online = (
        minecraft_process is not None
        and minecraft_process.poll() is None
    )

    return {
        "online": online,
        "minecraft_version": version or "-",
        "tipo": tipo or "-",
        "plataforma": plataforma or "Vanilla",
        "ram": ram,
        "ip": obtener_ip_playit() or "",
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "console": CONSOLA_BUFFER[-30000:] if CONSOLA_BUFFER else "",
        "properties": propiedades(),
        "whitelist": nombres_archivo("whitelist.json"),
        "banned": nombres_archivo("banned-players.json"),
        "ops": nombres_archivo("ops.json")
    }


def enviar_comando(cmd):
    """Escribe un comando en el stdin del proceso de Minecraft (usado
    por el botón STOP y la caja de comandos del dashboard)."""

    global CONSOLA_BUFFER

    with minecraft_lock:
        p = minecraft_process

        if not p or p.poll() is not None or not p.stdin:
            return False

        try:
            p.stdin.write(cmd + "\n")
            p.stdin.flush()

            CONSOLA_BUFFER += f"> {cmd}\n"

            if len(CONSOLA_BUFFER) > 30000:
                CONSOLA_BUFFER = CONSOLA_BUFFER[-30000:]

            return True
        except Exception:
            return False


def _bucle_lectura_proceso(proceso):
    """Lee la salida del proceso en segundo plano y la vuelca al
    buffer del dashboard, para que /api/start pueda arrancar el
    servidor sin bloquear la petición HTTP."""

    global minecraft_process

    try:
        for linea in iter(proceso.stdout.readline, ""):

            if not linea:
                break

            _procesar_linea_consola(linea)

        proceso.wait()

    except Exception:
        pass

    finally:

        with minecraft_lock:
            if minecraft_process is proceso:
                minecraft_process = None


def iniciar_proceso_minecraft():
    """Arranca el servidor de Minecraft de forma no interactiva.
    La usan tanto el menú de consola (opción 1) como el dashboard
    (botones Iniciar/Reiniciar)."""

    global minecraft_process, CONSOLA_BUFFER

    with minecraft_lock:
        if (
            minecraft_process is not None
            and minecraft_process.poll() is None
        ):
            return False, "El servidor ya está en ejecución."

    version, tipo, plataforma, ram = obtener_configuracion()

    if not version or not tipo:
        return False, "No hay un servidor configurado."

    if not instalar_java():
        return False, "Java 21 no está disponible."

    if not asegurar_servidor():
        return False, "No se pudo preparar el servidor."

    aceptar_eula()

    CONSOLA_BUFFER = ""

    comando = [
        "java",
        f"-Xmx{ram}G",
        "-jar",
        "server.jar",
        "--nogui"
    ]

    try:
        proceso = subprocess.Popen(
            comando,
            cwd=SERVER_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

    except Exception as error:
        return False, f"Error iniciando Minecraft: {error}"

    with minecraft_lock:
        minecraft_process = proceso

    threading.Thread(
        target=_bucle_lectura_proceso,
        args=(proceso,),
        daemon=True
    ).start()

    return True, "Servidor iniciando..."


def _reiniciar_tras_apagado():
    """Espera a que el proceso actual termine (tras un stop) y
    vuelve a lanzarlo. Usado por el botón Reiniciar del dashboard."""

    for _ in range(120):

        with minecraft_lock:
            activo = (
                minecraft_process is not None
                and minecraft_process.poll() is None
            )

        if not activo:
            break

        time.sleep(1)

    iniciar_proceso_minecraft()


class Handler(http.server.SimpleHTTPRequestHandler):

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DASHBOARD_DIR, **kw)

    def _json(self, d, code=200):

        b = json.dumps(d, ensure_ascii=False).encode()

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()

        self.wfile.write(b)

    def do_GET(self):

        if self.path.startswith("/api/status"):
            return self._json(dashboard_data())

        return super().do_GET()

    def _leer_json(self):

        n = int(self.headers.get("Content-Length", "0") or "0")
        crudo = self.rfile.read(n) if n else b""

        try:
            return json.loads(crudo or b"{}")
        except Exception:
            return None

    def do_POST(self):

        if self.path == "/api/console":

            if (
                minecraft_process is None
                or minecraft_process.poll() is not None
            ):
                return self._json(
                    {
                        "ok": False,
                        "message": "El servidor está apagado."
                    },
                    400
                )

            cuerpo = self._leer_json()

            if cuerpo is None:
                return self._json(
                    {"ok": False, "message": "JSON inválido"},
                    400
                )

            cmd = str(cuerpo.get("command", "")).strip()

            if not cmd:
                return self._json(
                    {"ok": False, "message": "Comando vacío."},
                    400
                )

            if len(cmd) > 500:
                return self._json(
                    {"ok": False, "message": "Comando demasiado largo."},
                    400
                )

            if enviar_comando(cmd):
                return self._json(
                    {"ok": True, "message": f"Enviado: {cmd}"}
                )

            return self._json(
                {"ok": False, "message": "No se pudo enviar el comando."},
                500
            )

        if self.path == "/api/player":

            cuerpo = self._leer_json()

            if cuerpo is None:
                return self._json(
                    {"ok": False, "message": "JSON inválido"},
                    400
                )

            ok, msg = accion_jugador(
                str(cuerpo.get("action", "")),
                str(cuerpo.get("name", ""))
            )

            return self._json(
                {"ok": ok, "message": msg},
                200 if ok else 400
            )

        if self.path == "/api/properties":

            if (
                minecraft_process is not None
                and minecraft_process.poll() is None
            ):
                return self._json(
                    {
                        "ok": False,
                        "message": (
                            "Detén el servidor antes de cambiar "
                            "server.properties."
                        )
                    },
                    409
                )

            cuerpo = self._leer_json()

            if cuerpo is None:
                return self._json(
                    {"ok": False, "message": "JSON inválido"},
                    400
                )

            cambios = {}

            for clave, valor in cuerpo.items():

                clave = str(clave)

                if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", clave):

                    valor = str(valor)

                    if valor.lower() in ("true", "false"):
                        valor = valor.lower()

                    cambios[clave] = valor

            guardar_propiedades(cambios)

            return self._json(
                {
                    "ok": True,
                    "message": (
                        "Propiedades guardadas. Reinicia el servidor "
                        "para aplicarlas."
                    )
                }
            )

        if self.path == "/api/start":

            ok, msg = iniciar_proceso_minecraft()

            return self._json(
                {"ok": ok, "message": msg},
                200 if ok else 400
            )

        if self.path == "/api/stop":

            if (
                minecraft_process is None
                or minecraft_process.poll() is not None
            ):
                return self._json(
                    {"ok": False, "message": "El servidor ya está apagado."},
                    400
                )

            if enviar_comando("stop"):
                return self._json(
                    {"ok": True, "message": "Comando STOP enviado."}
                )

            return self._json(
                {"ok": False, "message": "No se pudo enviar el comando STOP."},
                500
            )

        if self.path == "/api/restart":

            if (
                minecraft_process is not None
                and minecraft_process.poll() is None
            ):
                enviar_comando("stop")

            threading.Thread(
                target=_reiniciar_tras_apagado,
                daemon=True
            ).start()

            return self._json(
                {"ok": True, "message": "Reiniciando servidor..."}
            )

        return self._json(
            {"ok": False, "message": "Ruta no encontrada"},
            404
        )

    def log_message(self, *a):
        pass


class TCP(socketserver.TCPServer):
    allow_reuse_address = True


def iniciar_dashboard():
    """Levanta el servidor HTTP del dashboard en un hilo daemon.
    Esto es lo que faltaba: antes solo se escribía el HTML/JSON pero
    nada lo servía por HTTP, así que en Codespaces no había forma de
    llegar a él."""

    global dashboard_server

    generar_dashboard()

    if dashboard_server:
        return

    try:
        dashboard_server = TCP(("0.0.0.0", DASHBOARD_PORT), Handler)

        threading.Thread(
            target=dashboard_server.serve_forever,
            daemon=True
        ).start()

        print(
            f"\n{VERDE}🌐 Dashboard disponible en el puerto "
            f"{DASHBOARD_PORT}{RESET}"
        )

        print(
            f"{CIAN}   En Codespaces: pestaña 'PORTS' -> reenvía "
            f"{DASHBOARD_PORT} -> ábrelo en el navegador.{RESET}"
        )

    except OSError as error:

        print(
            f"\n{AMARILLO}⚠️ No se pudo iniciar el dashboard: "
            f"{error}{RESET}"
        )


def detener_dashboard():

    global dashboard_server

    if dashboard_server:

        try:
            dashboard_server.shutdown()
            dashboard_server.server_close()
        except Exception:
            pass

        dashboard_server = None


# ============================================================
# PLAYIT IP
# ============================================================

def extraer_ip_playit(linea):

    patrones = [
        r"found minecraft java tunnel:\s*([A-Za-z0-9._-]+)",
        r"minecraft java tunnel:\s*([A-Za-z0-9._-]+)",
        r"playit\.gg:\s*tunnel\s*setup.*?([A-Za-z0-9._-]+\.tun\.ply\.gg)",
    ]

    for patron in patrones:

        coincidencia = re.search(
            patron,
            linea,
            re.IGNORECASE
        )

        if coincidencia:

            direccion = coincidencia.group(1).strip()

            if direccion:
                return direccion

    return None


def guardar_ip_playit(ip):

    estado = cargar_estado()

    estado["playit"] = {
        "ip": ip,
        "updated": int(time.time())
    }

    guardar_estado(estado)


def obtener_ip_playit():

    estado = cargar_estado()

    playit = estado.get("playit", {})

    return playit.get("ip")


# ============================================================
# EULA
# ============================================================

def aceptar_eula():

    os.makedirs(
        SERVER_DIR,
        exist_ok=True
    )

    try:

        with open(
            EULA_FILE,
            "w",
            encoding="utf-8"
        ) as archivo:

            archivo.write(
                "# Minecraft EULA\n"
                "# Generated automatically.\n"
                "eula=true\n"
            )

        return True

    except Exception as error:

        print(
            f"\n{ROJO}"
            f"❌ No se pudo crear eula.txt:\n{error}"
            f"{RESET}"
        )

        return False


# ============================================================
# RAM
# ============================================================

def obtener_ram():

    estado = cargar_estado()

    launch = estado.get(
        "launch",
        {}
    )

    try:
        ram = int(
            launch.get(
                "ram_gb",
                8
            )
        )

    except Exception:
        ram = 8

    return max(
        1,
        ram
    )


def guardar_ram(ram):

    estado = cargar_estado()

    estado["launch"] = {
        "ram_gb": int(ram)
    }

    guardar_estado(estado)


# ============================================================
# JAVA
# ============================================================

def obtener_version_java():

    if not comando_existe("java"):
        return None

    try:

        resultado = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True
        )

    except Exception:
        return None

    texto = (
        resultado.stderr
        + resultado.stdout
    )

    coincidencia = re.search(
        r'version "(\d+)',
        texto
    )

    if coincidencia:
        return int(
            coincidencia.group(1)
        )

    return None


def instalar_java():

    version = obtener_version_java()

    if version and version >= 21:
        return True

    print(
        f"\n{AMARILLO}"
        "☕ Java 21 o superior es necesario."
        f"{RESET}"
    )

    if not comando_existe("apt"):

        print(
            f"{ROJO}"
            "❌ Este sistema no tiene apt."
            f"{RESET}"
        )

        return False

    if subprocess.run(
        ["sudo", "apt", "update"]
    ).returncode != 0:
        return False

    if subprocess.run(
        [
            "sudo",
            "apt",
            "install",
            "openjdk-21-jre",
            "-y"
        ]
    ).returncode != 0:
        return False

    version = obtener_version_java()

    return (
        version is not None
        and version >= 21
    )


# ============================================================
# MANIFEST
# ============================================================

def obtener_manifest():

    try:

        request = urllib.request.Request(
            VERSION_MANIFEST,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            return json.loads(
                respuesta.read()
            )

    except Exception as error:

        print(
            f"\n{ROJO}"
            f"❌ No se pudo consultar Mojang:\n{error}"
            f"{RESET}"
        )

        return None


def obtener_info_version(version):

    manifest = obtener_manifest()

    if manifest is None:
        return None

    for elemento in manifest.get(
        "versions",
        []
    ):

        if elemento.get("id") == version:
            return elemento

    return None


# ============================================================
# SELECCIÓN
# ============================================================

def seleccionar_version():

    while True:

        limpiar()

        print("""
╔══════════════════════════════════════════════════════╗
║              🟩 MINECRAFT SERVER SETUP              ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║        Escribe la versión de Minecraft.              ║
║                                                      ║
║        Ejemplo: 1.21.1                               ║
║        Ejemplo: 1.20.1                               ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        version = input(
            "Versión: "
        ).strip()

        if version.lower() == "salir":
            sys.exit(0)

        if not version:
            continue

        print(
            f"\n🌐 Comprobando Minecraft {version}..."
        )

        if obtener_info_version(version):

            print(
                f"{VERDE}"
                f"✅ Minecraft {version} encontrado."
                f"{RESET}"
            )

            time.sleep(1)

            return version

        print(
            f"{ROJO}"
            f"❌ Minecraft {version} no existe."
            f"{RESET}"
        )

        time.sleep(2)


def seleccionar_tipo():

    tipos = {
        "1": "Vanilla",
        "2": "Mods",
        "3": "Plugins"
    }

    while True:

        limpiar()

        print("""
╔══════════════════════════════════════════════════════╗
║                 🟩 TIPO DE SERVIDOR                 ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║        1. Vanilla                                   ║
║        2. Mods                                      ║
║        3. Plugins                                   ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        opcion = input(
            "Selecciona una opción: "
        ).strip()

        if opcion in tipos:
            return tipos[opcion]


def seleccionar_plataforma_mods():

    plataformas = {
        "1": "Forge",
        "2": "Fabric",
        "3": "NeoForge"
    }

    while True:

        limpiar()

        print("""
╔══════════════════════════════════════════════════════╗
║                     🧩 MODS                         ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║        1. Forge                                     ║
║        2. Fabric                                    ║
║        3. NeoForge                                  ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        opcion = input(
            "Selecciona una opción: "
        ).strip()

        if opcion in plataformas:
            return plataformas[opcion]


def seleccionar_plataforma_plugins():

    plataformas = {
        "1": "Paper",
        "2": "Spigot"
    }

    while True:

        limpiar()

        print("""
╔══════════════════════════════════════════════════════╗
║                   🔌 PLUGINS                        ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║        1. Paper                                     ║
║        2. Spigot                                    ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        opcion = input(
            "Selecciona una opción: "
        ).strip()

        if opcion in plataformas:
            return plataformas[opcion]


# ============================================================
# CONFIGURACIÓN
# ============================================================

def guardar_configuracion(
    version,
    tipo,
    plataforma=None
):

    estado = cargar_estado()

    estado["minecraft"] = {
        "version": version,
        "tipo": tipo,
        "plataforma": plataforma
    }

    if "launch" not in estado:

        estado["launch"] = {
            "ram_gb": 8
        }

    guardar_estado(estado)


def obtener_configuracion():

    estado = cargar_estado()

    minecraft = estado.get(
        "minecraft",
        {}
    )

    return (
        minecraft.get("version"),
        minecraft.get("tipo"),
        minecraft.get("plataforma"),
        obtener_ram()
    )


# ============================================================
# SERVIDOR
# ============================================================

def servidor_corresponde(
    version,
    tipo,
    plataforma
):

    if not os.path.exists(SERVER_JAR):
        return False

    if os.path.getsize(
        SERVER_JAR
    ) <= 0:
        return False

    info = cargar_server_info()

    if not info:
        return False

    return (
        info.get("minecraft_version") == version
        and info.get("tipo") == tipo
        and info.get("plataforma") == plataforma
    )


def descargar_archivo(
    url,
    destino
):

    try:

        os.makedirs(
            os.path.dirname(destino),
            exist_ok=True
        )

        temporal = (
            destino
            + ".downloading"
        )

        if os.path.exists(temporal):
            os.remove(temporal)

        print(
            f"\n{CIAN}"
            f"📥 Descargando:\n{url}"
            f"{RESET}"
        )

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=180
        ) as respuesta:

            with open(
                temporal,
                "wb"
            ) as archivo:

                shutil.copyfileobj(
                    respuesta,
                    archivo
                )

        if not os.path.exists(
            temporal
        ):
            return False

        if os.path.getsize(
            temporal
        ) <= 0:

            os.remove(
                temporal
            )

            return False

        os.replace(
            temporal,
            destino
        )

        return True

    except Exception as error:

        print(
            f"\n{ROJO}"
            f"❌ Error descargando:\n{error}"
            f"{RESET}"
        )

        temporal = (
            destino
            + ".downloading"
        )

        if os.path.exists(temporal):

            try:
                os.remove(
                    temporal
                )
            except Exception:
                pass

        return False


def obtener_url_server(version):

    info = obtener_info_version(
        version
    )

    if not info:
        return None

    try:

        request = urllib.request.Request(
            info["url"],
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            datos = json.loads(
                respuesta.read()
            )

        return (
            datos
            .get("downloads", {})
            .get("server", {})
            .get("url")
        )

    except Exception:
        return None


def descargar_vanilla(version):

    url = obtener_url_server(
        version
    )

    if not url:
        return False

    if not descargar_archivo(
        url,
        SERVER_JAR
    ):
        return False

    guardar_server_info(
        version,
        "Vanilla",
        None,
        version
    )

    aceptar_eula()

    return True


# ============================================================
# PAPER
# ============================================================

def obtener_paper_url(version):

    url = (
        "https://fill.papermc.io/v3/projects/"
        f"paper/versions/{version}/builds"
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            datos = json.loads(
                respuesta.read()
            )

        if not isinstance(
            datos,
            list
        ):
            return None

        estables = [
            build
            for build in datos
            if build.get("channel") == "STABLE"
        ]

        if not estables:
            return None

        build = estables[0]

        descarga = (
            build
            .get("downloads", {})
            .get("server:default")
        )

        if not descarga:
            return None

        return (
            descarga.get("url"),
            build.get("id")
        )

    except Exception:
        return None


def descargar_paper(version):

    resultado = obtener_paper_url(
        version
    )

    if not resultado:
        return False

    url, build = resultado

    if not descargar_archivo(
        url,
        SERVER_JAR
    ):
        return False

    guardar_server_info(
        version,
        "Plugins",
        "Paper",
        str(build)
    )

    aceptar_eula()

    return True


# ============================================================
# PLAYIT
# ============================================================

def descargar_playit_plugin():

    os.makedirs(
        PLUGINS_DIR,
        exist_ok=True
    )

    if os.path.exists(
        PLAYIT_PLUGIN_FILE
    ):

        try:

            if os.path.getsize(
                PLAYIT_PLUGIN_FILE
            ) > 10000:

                return True

        except Exception:
            pass

        try:
            os.remove(
                PLAYIT_PLUGIN_FILE
            )
        except Exception:
            pass

    return descargar_archivo(
        PLAYIT_PLUGIN_URL,
        PLAYIT_PLUGIN_FILE
    )


def asegurar_plugin_playit():

    version, tipo, plataforma, _ = (
        obtener_configuracion()
    )

    if not version:
        return False

    if plataforma not in (
        "Paper",
        "Spigot"
    ):
        return False

    return descargar_playit_plugin()


# ============================================================
# FABRIC
# ============================================================

def obtener_fabric_server_url(version):

    base = "https://meta.fabricmc.net/v2/"

    try:

        request = urllib.request.Request(
            base + f"versions/loader/{version}",
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            loaders = json.loads(
                respuesta.read()
            )

        if not loaders:
            return None

        loader = loaders[0]["loader"]["version"]

        request = urllib.request.Request(
            base + "versions/installer",
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            installers = json.loads(
                respuesta.read()
            )

        if not installers:
            return None

        installer = installers[0]["version"]

        url = (
            base
            + f"versions/loader/{version}/"
            + f"{loader}/{installer}/server/jar"
        )

        return (
            url,
            loader,
            installer
        )

    except Exception:
        return None


def descargar_fabric(version):

    resultado = obtener_fabric_server_url(
        version
    )

    if not resultado:
        return False

    url, loader, installer = resultado

    if not descargar_archivo(
        url,
        SERVER_JAR
    ):
        return False

    guardar_server_info(
        version,
        "Mods",
        "Fabric",
        loader
    )

    aceptar_eula()

    return True


# ============================================================
# FORGE
# ============================================================

def obtener_forge_version(version):

    url = (
        "https://files.minecraftforge.net/"
        "net/minecraftforge/forge/"
        "promotions_slim.json"
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            datos = json.loads(
                respuesta.read()
            )

        promos = datos.get(
            "promos",
            {}
        )

        return (
            promos.get(
                f"{version}-recommended"
            )
            or
            promos.get(
                f"{version}-latest"
            )
        )

    except Exception:
        return None


def descargar_forge(version):

    forge_version = obtener_forge_version(
        version
    )

    if not forge_version:
        return False

    installer_name = (
        f"forge-{version}-{forge_version}-installer.jar"
    )

    installer_url = (
        "https://maven.minecraftforge.net/"
        "net/minecraftforge/forge/"
        f"{version}-{forge_version}/"
        f"{installer_name}"
    )

    installer_path = os.path.join(
        SERVER_DIR,
        installer_name
    )

    if not descargar_archivo(
        installer_url,
        installer_path
    ):
        return False

    resultado = subprocess.run(
        [
            "java",
            "-jar",
            installer_name,
            "--installServer"
        ],
        cwd=SERVER_DIR
    )

    if resultado.returncode != 0:
        return False

    candidatos = []

    for archivo in os.listdir(
        SERVER_DIR
    ):

        nombre = archivo.lower()

        if (
            nombre.endswith(".jar")
            and (
                "server" in nombre
                or "forge" in nombre
            )
            and archivo != installer_name
            and archivo != "server.jar"
        ):

            candidatos.append(
                archivo
            )

    if not candidatos:
        return False

    candidatos.sort()

    origen = os.path.join(
        SERVER_DIR,
        candidatos[-1]
    )

    if os.path.exists(
        SERVER_JAR
    ):
        os.remove(
            SERVER_JAR
        )

    shutil.move(
        origen,
        SERVER_JAR
    )

    guardar_server_info(
        version,
        "Mods",
        "Forge",
        forge_version
    )

    aceptar_eula()

    return True


# ============================================================
# NEOFORGE
# ============================================================

def obtener_neoforge_version(version):

    url = (
        "https://maven.neoforged.net/"
        "releases/net/neoforged/neoforge/"
        "maven-metadata.xml"
    )

    try:

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as respuesta:

            texto = respuesta.read().decode(
                "utf-8"
            )

        versiones = re.findall(
            r"<version>([^<]+)</version>",
            texto
        )

        partes = version.split(".")

        if len(partes) < 2:
            return None

        if partes[0] == "1":

            if len(partes) >= 3:
                prefijo = (
                    f"{partes[1]}.{partes[2]}."
                )

            else:
                prefijo = (
                    f"{partes[1]}."
                )

        else:
            prefijo = (
                f"{partes[0]}."
            )

        compatibles = [
            v
            for v in versiones
            if v.startswith(prefijo)
        ]

        if not compatibles:
            return None

        compatibles.sort(
            reverse=True
        )

        return compatibles[0]

    except Exception:
        return None


def descargar_neoforge(version):

    neoforge_version = (
        obtener_neoforge_version(
            version
        )
    )

    if not neoforge_version:
        return False

    installer_name = (
        f"neoforge-{neoforge_version}-installer.jar"
    )

    installer_url = (
        "https://maven.neoforged.net/"
        "releases/net/neoforged/neoforge/"
        f"{neoforge_version}/"
        f"{installer_name}"
    )

    installer_path = os.path.join(
        SERVER_DIR,
        installer_name
    )

    if not descargar_archivo(
        installer_url,
        installer_path
    ):
        return False

    resultado = subprocess.run(
        [
            "java",
            "-jar",
            installer_name,
            "--installServer"
        ],
        cwd=SERVER_DIR
    )

    if resultado.returncode != 0:
        return False

    candidatos = []

    for archivo in os.listdir(
        SERVER_DIR
    ):

        nombre = archivo.lower()

        if (
            nombre.endswith(".jar")
            and "neoforge" in nombre
            and archivo != installer_name
            and archivo != "server.jar"
        ):

            candidatos.append(
                archivo
            )

    if not candidatos:
        return False

    candidatos.sort()

    origen = os.path.join(
        SERVER_DIR,
        candidatos[-1]
    )

    if os.path.exists(
        SERVER_JAR
    ):
        os.remove(
            SERVER_JAR
        )

    shutil.move(
        origen,
        SERVER_JAR
    )

    guardar_server_info(
        version,
        "Mods",
        "NeoForge",
        neoforge_version
    )

    aceptar_eula()

    return True


# ============================================================
# SPIGOT
# ============================================================

def descargar_spigot(version):

    buildtools_url = (
        "https://hub.spigotmc.org/"
        "jenkins/job/BuildTools/"
        "lastSuccessfulBuild/artifact/"
        "target/BuildTools.jar"
    )

    buildtools = os.path.join(
        SERVER_DIR,
        "BuildTools.jar"
    )

    if not os.path.exists(
        buildtools
    ):

        if not descargar_archivo(
            buildtools_url,
            buildtools
        ):
            return False

    resultado = subprocess.run(
        [
            "java",
            "-jar",
            "BuildTools.jar",
            "--rev",
            version
        ],
        cwd=SERVER_DIR
    )

    if resultado.returncode != 0:
        return False

    candidatos = [
        archivo
        for archivo in os.listdir(
            SERVER_DIR
        )
        if (
            archivo.startswith(
                "spigot-"
            )
            and archivo.endswith(
                ".jar"
            )
        )
    ]

    if not candidatos:
        return False

    candidatos.sort()

    origen = os.path.join(
        SERVER_DIR,
        candidatos[-1]
    )

    if os.path.exists(
        SERVER_JAR
    ):
        os.remove(
            SERVER_JAR
        )

    shutil.move(
        origen,
        SERVER_JAR
    )

    guardar_server_info(
        version,
        "Plugins",
        "Spigot",
        version
    )

    aceptar_eula()

    return True


# ============================================================
# PREPARAR SERVIDOR
# ============================================================

def descargar_servidor(
    version,
    tipo,
    plataforma
):

    os.makedirs(
        SERVER_DIR,
        exist_ok=True
    )

    if servidor_corresponde(
        version,
        tipo,
        plataforma
    ):

        aceptar_eula()

        if plataforma in (
            "Paper",
            "Spigot"
        ):
            asegurar_plugin_playit()

        return True

    if os.path.exists(
        SERVER_JAR
    ):

        try:
            os.remove(
                SERVER_JAR
            )

        except Exception as error:

            print(
                f"{ROJO}"
                f"❌ No se pudo reemplazar server.jar:\n"
                f"{error}"
                f"{RESET}"
            )

            return False

    if tipo == "Vanilla":
        return descargar_vanilla(
            version
        )

    if (
        tipo == "Plugins"
        and plataforma == "Paper"
    ):

        if not descargar_paper(
            version
        ):
            return False

        return asegurar_plugin_playit()

    if (
        tipo == "Plugins"
        and plataforma == "Spigot"
    ):

        if not descargar_spigot(
            version
        ):
            return False

        return asegurar_plugin_playit()

    if (
        tipo == "Mods"
        and plataforma == "Fabric"
    ):
        return descargar_fabric(
            version
        )

    if (
        tipo == "Mods"
        and plataforma == "Forge"
    ):
        return descargar_forge(
            version
        )

    if (
        tipo == "Mods"
        and plataforma == "NeoForge"
    ):
        return descargar_neoforge(
            version
        )

    return False


def asegurar_servidor():

    version, tipo, plataforma, ram = (
        obtener_configuracion()
    )

    if not version or not tipo:
        return False

    os.makedirs(
        SERVER_DIR,
        exist_ok=True
    )

    if not servidor_corresponde(
        version,
        tipo,
        plataforma
    ):

        return descargar_servidor(
            version,
            tipo,
            plataforma
        )

    aceptar_eula()

    if plataforma in (
        "Paper",
        "Spigot"
    ):

        if not asegurar_plugin_playit():
            return False

    return True


def configurar_servidor():

    version = seleccionar_version()
    tipo = seleccionar_tipo()

    plataforma = None

    if tipo == "Mods":
        plataforma = seleccionar_plataforma_mods()

    elif tipo == "Plugins":
        plataforma = seleccionar_plataforma_plugins()

    guardar_configuracion(
        version,
        tipo,
        plataforma
    )

    limpiar()

    print("""
╔══════════════════════════════════════════════════════╗
║                📦 PREPARANDO SERVIDOR               ║
╚══════════════════════════════════════════════════════╝
""")

    if descargar_servidor(
        version,
        tipo,
        plataforma
    ):

        aceptar_eula()

        print(
            f"\n{VERDE}"
            "✅ Servidor preparado."
            f"{RESET}"
        )

    else:

        print(
            f"\n{ROJO}"
            "❌ No se pudo preparar el servidor."
            f"{RESET}"
        )

    pausa()


# ============================================================
# RAM
# ============================================================

def configurar_ram():

    while True:

        limpiar()

        ram_actual = obtener_ram()

        print("""
╔══════════════════════════════════════════════════════╗
║                  ⚙️ CONFIGURAR RAM                   ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║   Escribe la cantidad de GB que quieres utilizar.   ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        print(
            f"RAM actual: {ram_actual} GB"
        )

        entrada = input(
            "\nNueva RAM en GB: "
        ).strip()

        if not entrada:
            return

        try:
            ram = int(
                entrada
            )

        except ValueError:

            print(
                f"\n{ROJO}"
                "❌ Debe ser un número entero."
                f"{RESET}"
            )

            time.sleep(1)
            continue

        if ram < 1:

            print(
                f"\n{ROJO}"
                "❌ La RAM mínima es 1 GB."
                f"{RESET}"
            )

            time.sleep(1)
            continue

        guardar_ram(
            ram
        )

        print(
            f"\n{VERDE}"
            f"✅ RAM configurada: {ram} GB."
            f"{RESET}"
        )

        time.sleep(1)

        return


# ============================================================
# BORRAR
# ============================================================

def borrar_servidor():

    limpiar()

    print(
        f"{ROJO}"
        """
╔══════════════════════════════════════════════════════╗
║              ⚠️ BORRAR SERVIDOR ⚠️                  ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  Se eliminará TODO minecraft-server/                ║
║                                                      ║
║  Incluye mundo, mods, plugins, server.jar y EULA.   ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
"""
        + RESET
    )

    print(
        f"{AMARILLO}"
        "\nEscribe exactamente: BORRAR SERVIDOR"
        f"{RESET}"
    )

    confirmacion = input(
        "\nConfirmación: "
    ).strip()

    if confirmacion != "BORRAR SERVIDOR":

        print(
            f"\n{VERDE}"
            "✅ Cancelado."
            f"{RESET}"
        )

        time.sleep(2)

        return

    if os.path.exists(
        SERVER_DIR
    ):

        try:
            shutil.rmtree(
                SERVER_DIR
            )

        except Exception as error:

            print(
                f"\n{ROJO}"
                f"❌ Error:\n{error}"
                f"{RESET}"
            )

            pausa()
            return

    estado = cargar_estado()

    estado.pop(
        "minecraft",
        None
    )

    estado.pop(
        "launch",
        None
    )

    estado.pop(
        "playit",
        None
    )

    guardar_estado(
        estado
    )

    print(
        f"\n{VERDE}"
        "✅ Servidor eliminado completamente."
        f"{RESET}"
    )

    pausa()


# ============================================================
# LANZAR SERVIDOR
# (usa iniciar_proceso_minecraft(), compartido con el dashboard)
# ============================================================

def lanzar_servidor():

    version, tipo, plataforma, ram = (
        obtener_configuracion()
    )

    if not version or not tipo:

        print(
            f"\n{ROJO}"
            "❌ No hay un servidor configurado."
            f"{RESET}"
        )

        pausa()

        return

    limpiar()

    plataforma_mostrar = (
        plataforma or "Vanilla"
    )

    print("""
╔══════════════════════════════════════════════════════╗
║                 🚀 SERVIDOR MINECRAFT               ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
""")

    print(
        f"║   Minecraft:  {str(version):<36}║"
    )

    print(
        f"║   Tipo:       {str(tipo):<36}║"
    )

    print(
        f"║   Plataforma: {str(plataforma_mostrar):<36}║"
    )

    print(
        f"║   RAM:        {str(ram) + ' GB':<36}║"
    )

    print("""
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

    if plataforma in (
        "Paper",
        "Spigot"
    ):

        ip_anterior = obtener_ip_playit()

        print(
            f"{CIAN}"
            "🌐 PLAYIT"
            f"{RESET}"
        )

        if ip_anterior:
            print(
                f"IP anterior: {ip_anterior}"
            )

        print(
            "⏳ Esperando a que Playit entregue "
            "la dirección pública..."
        )

        print()

    print(
        f"{VERDE}"
        "🚀 Iniciando Minecraft..."
        f"{RESET}\n"
    )

    # Nos aseguramos de que el dashboard esté arriba (normalmente
    # ya lo está desde main(), pero por si se llegó aquí de otra
    # forma no está de más).
    iniciar_dashboard()

    ok, mensaje = iniciar_proceso_minecraft()

    if not ok:

        print(
            f"\n{ROJO}"
            f"❌ {mensaje}"
            f"{RESET}"
        )

        pausa()

        return

    ultimo_len = 0
    ip_mostrada = False

    try:

        while True:

            buffer_actual = CONSOLA_BUFFER

            if len(buffer_actual) > ultimo_len:

                print(
                    buffer_actual[ultimo_len:],
                    end="",
                    flush=True
                )

                ultimo_len = len(buffer_actual)

            ip = obtener_ip_playit()

            if (
                ip
                and not ip_mostrada
                and plataforma in ("Paper", "Spigot")
            ):

                print()

                print(
                    f"{VERDE}"
                    "╔══════════════════════════════════════════════════════╗"
                    f"{RESET}"
                )

                print(
                    f"{VERDE}"
                    "║                 🌐 SERVIDOR ONLINE                 ║"
                    f"{RESET}"
                )

                print(
                    f"{VERDE}"
                    "╠══════════════════════════════════════════════════════╣"
                    f"{RESET}"
                )

                print(
                    f"{VERDE}"
                    f"║   IP: {ip:<44}║"
                    f"{RESET}"
                )

                print(
                    f"{VERDE}"
                    "╚══════════════════════════════════════════════════════╝"
                    f"{RESET}"
                )

                print()

                ip_mostrada = True

            with minecraft_lock:
                sigue_vivo = (
                    minecraft_process is not None
                    and minecraft_process.poll() is None
                )

            if not sigue_vivo:
                break

            time.sleep(0.5)

        print(
            f"\n{AMARILLO}"
            "⚠️ Minecraft se detuvo."
            f"{RESET}"
        )

    except KeyboardInterrupt:

        print(
            f"\n{AMARILLO}"
            "⚠️ Interrupción detectada. El servidor sigue accesible "
            "desde el dashboard (el proceso no se mató)."
            f"{RESET}"
        )

    pausa()


# ============================================================
# INTERFAZ
# ============================================================

def interfaz():

    while True:

        version, tipo, plataforma, ram = (
            obtener_configuracion()
        )

        limpiar()

        plataforma_mostrar = (
            plataforma
            if plataforma
            else "Vanilla"
        )

        print("""
╔══════════════════════════════════════════════════════╗
║              🟩 MINECRAFT SERVER                    ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
""")

        print(
            f"║   Minecraft:  {str(version or 'No configurado'):<36}║"
        )

        print(
            f"║   Tipo:       {str(tipo or 'No configurado'):<36}║"
        )

        print(
            f"║   Plataforma: {str(plataforma_mostrar):<36}║"
        )

        print(
            f"║   RAM:        {str(ram) + ' GB':<36}║"
        )

        ip = obtener_ip_playit()

        if ip and plataforma in (
            "Paper",
            "Spigot"
        ):

            print(
                f"║   Playit:     {str(ip):<36}║"
            )

        print("""
║                                                      ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║          1. 🚀 Lanzar servidor                       ║
║          2. ⚙️  Configurar servidor                  ║
║          3. 💾 Configurar RAM                        ║
║          4. 🌐 Ver info del dashboard                ║
║          5. 🗑️  Borrar servidor                      ║
║          6. ❌ Salir                                  ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

        opcion = input(
            "Selecciona una opción: "
        ).strip()

        if opcion == "1":
            lanzar_servidor()

        elif opcion == "2":
            configurar_servidor()

        elif opcion == "3":
            configurar_ram()

        elif opcion == "4":

            iniciar_dashboard()

            print(
                f"\n{VERDE}"
                "✅ Dashboard corriendo en el puerto "
                f"{DASHBOARD_PORT}."
                f"{RESET}"
            )

            print(
                f"\n{CIAN}"
                "En Codespaces abre la pestaña 'PORTS', reenvía "
                f"{DASHBOARD_PORT} y ábrelo en el navegador."
                f"{RESET}"
            )

            pausa()

        elif opcion == "5":
            borrar_servidor()

        elif opcion == "6":

            print(
                "\n👋 Hasta luego."
            )

            return

        else:

            print(
                f"\n{ROJO}"
                "❌ Opción no válida."
                f"{RESET}"
            )

            time.sleep(1)


# ============================================================
# PRIMERA CONFIGURACIÓN
# ============================================================

def primera_configuracion():

    version, tipo, plataforma, ram = (
        obtener_configuracion()
    )

    if version and tipo:

        aceptar_eula()

        if plataforma in (
            "Paper",
            "Spigot"
        ):
            asegurar_plugin_playit()

        return True

    limpiar()

    print("""
╔══════════════════════════════════════════════════════╗
║             🟩 PRIMERA CONFIGURACIÓN                ║
╠══════════════════════════════════════════════════════╣
║                                                      ║
║  Vamos a configurar tu servidor Minecraft.           ║
║                                                      ║
║  Para Paper/Spigot se instalará el plugin             ║
║  de Playit directamente en plugins/.                 ║
║                                                      ║
║  También se generará un dashboard visual.            ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
""")

    pausa()

    if not instalar_java():

        print(
            f"\n{ROJO}"
            "❌ Java 21 no está disponible."
            f"{RESET}"
        )

        pausa()

        return False

    version = seleccionar_version()
    tipo = seleccionar_tipo()

    plataforma = None

    if tipo == "Mods":
        plataforma = seleccionar_plataforma_mods()

    elif tipo == "Plugins":
        plataforma = seleccionar_plataforma_plugins()

    guardar_configuracion(
        version,
        tipo,
        plataforma
    )

    if not descargar_servidor(
        version,
        tipo,
        plataforma
    ):

        print(
            f"\n{ROJO}"
            "❌ No se pudo preparar el servidor."
            f"{RESET}"
        )

        pausa()

        return False

    aceptar_eula()

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    # El dashboard se levanta ya al arrancar el script, no solo al
    # lanzar el servidor de Minecraft: así en Codespaces el puerto
    # queda disponible para reenviar desde el primer segundo.
    iniciar_dashboard()

    try:

        if not primera_configuracion():
            return

        interfaz()

    except KeyboardInterrupt:

        print(
            f"\n\n{AMARILLO}"
            "⚠️ Programa detenido."
            f"{RESET}"
        )

    except Exception as error:

        print(
            f"\n{ROJO}"
            f"❌ Error inesperado:\n{error}"
            f"{RESET}"
        )

        pausa()


if __name__ == "__main__":
    main()
