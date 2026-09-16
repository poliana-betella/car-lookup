# -*- coding: utf-8 -*-
"""
CAR Lookup - plugin QGIS
Baixa o poligono de um imovel do CAR/SICAR pelo codigo, em GeoJSON,
usando o geoservico (WFS) publico do CAR.
"""
import os
import re
import json
import ssl
import urllib.request
import urllib.parse
from xml.etree import ElementTree as ET

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAction,
    QInputDialog,
    QMessageBox,
    QApplication,
)
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsVectorLayer, QgsProject, QgsSettings, QgsMessageLog, Qgis

WFS_BASE = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
SETTINGS_TYPENAME_BY_UF = "car_lookup/typename_by_uf"  # JSON: {"MG": "sicar:AREA_IMOVEL_MG", ...}
SETTINGS_FIELD_BY_TYPENAME = "car_lookup/field_by_typename"  # JSON: {typename: "cod_imovel"}
LOG_TAG = "CAR Lookup"

UF_SET = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

# Nomes de campo mais comuns usados em bases do SICAR/CAR.
# O plugin tenta cada um ate achar o que funciona, e depois lembra qual foi.
FIELD_CANDIDATES = ["cod_imovel", "COD_IMOVEL", "cd_imovel", "codimovel", "CODIMOVEL"]


def _extract_uf(cod_imovel):
    """Extrai a sigla do estado do inicio do codigo do CAR, ex: 'MG-3134301-...' -> 'MG'."""
    match = re.match(r"^\s*([A-Za-z]{2})", cod_imovel)
    if not match:
        return None
    uf = match.group(1).upper()
    return uf if uf in UF_SET else None


def _load_json_setting(key, default):
    settings = QgsSettings()
    raw = settings.value(key, None)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _save_json_setting(key, value):
    QgsSettings().setValue(key, json.dumps(value))


def _build_ssl_contexts():
    """
    Alguns servidores do governo (o do CAR entre eles) usam configuracoes
    de TLS/cifras antigas que o OpenSSL 3 recusa por padrao (SECLEVEL 2).
    Aqui montamos uma lista de contextos, do mais restrito ao mais
    permissivo, e tentamos em ordem ate um funcionar.
    """
    contexts = []

    ctx1 = ssl.create_default_context()
    contexts.append(("padrao", ctx1))

    ctx2 = ssl.create_default_context()
    try:
        ctx2.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    contexts.append(("seclevel1", ctx2))

    ctx3 = ssl.create_default_context()
    try:
        ctx3.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx3.minimum_version = ssl.TLSVersion.TLSv1
    except Exception:
        pass
    contexts.append(("seclevel1_tls1", ctx3))

    ctx4 = ssl._create_unverified_context()
    try:
        ctx4.set_ciphers("DEFAULT@SECLEVEL=1")
    except Exception:
        pass
    contexts.append(("sem_verificacao", ctx4))

    return contexts


def _http_get(url, timeout=40):
    settings = QgsSettings()
    preferred = settings.value("car_lookup/ssl_mode", None)
    contexts = _build_ssl_contexts()

    if preferred:
        contexts.sort(key=lambda item: 0 if item[0] == preferred else 1)

    last_error = None
    for label, ctx in contexts:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "QGIS-CAR-Lookup-Plugin"}
            )
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = resp.read()
            settings.setValue("car_lookup/ssl_mode", label)
            return data
        except Exception as e:
            last_error = e
            QgsMessageLog.logMessage(
                f"Falha de conexao com modo SSL '{label}': {e}", LOG_TAG, level=Qgis.Info
            )
            continue

    raise last_error


class CarLookupPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.actions = []
        self.menu = "&CAR Lookup"

    def initGui(self):
        icon = QIcon()  # sem icone customizado; usa o padrao do Qt
        self.action = QAction("Baixar imovel do CAR por codigo...", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToWebMenu(self.menu, self.action)
        self.actions.append(self.action)

        self.reset_action = QAction("Redetectar camada/campo do WFS", self.iface.mainWindow())
        self.reset_action.triggered.connect(self.reset_cache)
        self.iface.addPluginToWebMenu(self.menu, self.reset_action)
        self.actions.append(self.reset_action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginWebMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

    def reset_cache(self):
        settings = QgsSettings()
        settings.remove(SETTINGS_TYPENAME_BY_UF)
        settings.remove(SETTINGS_FIELD_BY_TYPENAME)
        QMessageBox.information(
            self.iface.mainWindow(),
            "CAR Lookup",
            "Cache limpo. Na proxima consulta o plugin vai redetectar a camada e o campo automaticamente.",
        )

    # ------------------------------------------------------------------
    # Descoberta automatica da camada (typeName) no WFS, por UF.
    # A base do CAR e' dividida em uma camada por estado (ex: AREA_IMOVEL_MG),
    # entao cacheamos um typeName diferente para cada sigla de estado.
    # ------------------------------------------------------------------
    def discover_typename(self, uf, cod_imovel):
        typename_by_uf = _load_json_setting(SETTINGS_TYPENAME_BY_UF, {})
        if uf and uf in typename_by_uf:
            return typename_by_uf[uf]

        url = WFS_BASE + "?" + urllib.parse.urlencode(
            {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}
        )
        try:
            data = _http_get(url)
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "CAR Lookup",
                "Nao foi possivel acessar o geoservico do CAR agora.\n\n"
                "Verifique sua internet ou tente novamente mais tarde.\n\n"
                f"Detalhe tecnico: {e}",
            )
            return None

        try:
            root = ET.fromstring(data)
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "CAR Lookup",
                f"Resposta do GetCapabilities veio em formato inesperado: {e}",
            )
            return None

        names = []
        for el in root.iter():
            tag = el.tag.split("}")[-1]  # ignora namespace
            if tag == "Name" and el.text:
                names.append(el.text.strip())

        # remove duplicatas mantendo ordem
        seen = set()
        names = [n for n in names if not (n in seen or seen.add(n))]

        candidates = [n for n in names if "imovel" in n.lower() or "area" in n.lower()]
        pool = candidates if candidates else names

        if not pool:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "CAR Lookup",
                "Nenhuma camada foi listada pelo servico WFS do CAR. O servico pode estar fora do ar.",
            )
            return None

        # Tenta casar a UF extraida do codigo com o nome da camada
        # (ex: uf="MG" bate em "sicar:AREA_IMOVEL_MG", "sicar:mg_imovel", etc.)
        chosen = None
        if uf:
            uf_matches = [
                n for n in pool
                if re.search(rf"(^|[_:\-]){uf}([_:\-]|$)", n, flags=re.IGNORECASE)
            ]
            if len(uf_matches) == 1:
                chosen = uf_matches[0]
            elif len(uf_matches) > 1:
                pool = uf_matches  # restringe a lista pro usuario so' se ainda houver ambiguidade

        if not chosen:
            if len(pool) == 1:
                chosen = pool[0]
            else:
                chosen, ok = QInputDialog.getItem(
                    self.iface.mainWindow(),
                    "CAR Lookup - selecione a camada",
                    (
                        f"Nao consegui casar automaticamente a UF '{uf}' do codigo "
                        f"'{cod_imovel}' com uma camada. Selecione a camada correta "
                        "na lista (normalmente contem 'imovel' ou 'area' no nome):"
                        if uf else
                        "Nao foi possivel extrair a UF do codigo informado. Selecione "
                        "a camada correta na lista:"
                    ),
                    pool,
                    0,
                    False,
                )
                if not ok:
                    return None

        if uf:
            typename_by_uf[uf] = chosen
            _save_json_setting(SETTINGS_TYPENAME_BY_UF, typename_by_uf)

        return chosen

    # ------------------------------------------------------------------
    # Busca da feicao por codigo do imovel, testando os nomes de campo
    # mais comuns ate encontrar um que retorne resultado.
    # ------------------------------------------------------------------
    def fetch_feature_geojson(self, typename, cod_imovel):
        field_by_typename = _load_json_setting(SETTINGS_FIELD_BY_TYPENAME, {})
        cached_field = field_by_typename.get(typename)
        fields_to_try = [cached_field] + FIELD_CANDIDATES if cached_field else FIELD_CANDIDATES

        last_error = None
        for field in fields_to_try:
            if not field:
                continue
            cql = "{}='{}'".format(field, cod_imovel.replace("'", ""))
            params = {
                "service": "WFS",
                "version": "2.0.0",
                "request": "GetFeature",
                "typeNames": typename,
                "outputFormat": "application/json",
                "CQL_FILTER": cql,
            }
            url = WFS_BASE + "?" + urllib.parse.urlencode(params)
            try:
                raw = _http_get(url)
                gj = json.loads(raw)
            except Exception as e:
                last_error = e
                QgsMessageLog.logMessage(
                    f"Falha tentando campo '{field}': {e}", LOG_TAG, level=Qgis.Info
                )
                continue

            if gj.get("features"):
                field_by_typename[typename] = field
                _save_json_setting(SETTINGS_FIELD_BY_TYPENAME, field_by_typename)
                return raw, field

        if last_error:
            QgsMessageLog.logMessage(
                f"Ultimo erro de consulta: {last_error}", LOG_TAG, level=Qgis.Warning
            )
        return None, None

    # ------------------------------------------------------------------
    # Acao principal
    # ------------------------------------------------------------------
    def run(self):
        cod, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "CAR Lookup",
            "Codigo do imovel no CAR (ex: SP-3550308-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX):",
        )
        if not ok or not cod.strip():
            return
        cod = cod.strip()
        uf = _extract_uf(cod)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            typename = self.discover_typename(uf, cod)
            if not typename:
                return

            raw, field_used = self.fetch_feature_geojson(typename, cod)
        finally:
            QApplication.restoreOverrideCursor()

        if not raw:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "CAR Lookup",
                "Nenhum imovel encontrado com esse codigo (ou o campo de "
                "codigo da base mudou de nome). Confira o codigo digitado.\n\n"
                "Se tiver certeza que o codigo esta certo, use o menu "
                "'Redetectar camada/campo do WFS' e tente de novo.",
            )
            return

        out_dir = os.path.join(os.path.expanduser("~"), "CAR_downloads")
        os.makedirs(out_dir, exist_ok=True)
        safe_name = "".join(c for c in cod if c.isalnum() or c in "-_")
        out_path = os.path.join(out_dir, f"{safe_name}.geojson")

        with open(out_path, "wb") as f:
            f.write(raw)

        layer = QgsVectorLayer(out_path, f"CAR_{safe_name}", "ogr")
        if not layer.isValid():
            QMessageBox.critical(
                self.iface.mainWindow(),
                "CAR Lookup",
                f"O arquivo foi baixado em:\n{out_path}\n\nmas o QGIS nao "
                "conseguiu abri-lo como camada valida.",
            )
            return

        QgsProject.instance().addMapLayer(layer)
        self.iface.mapCanvas().setExtent(layer.extent())
        self.iface.mapCanvas().refresh()

        self.iface.messageBar().pushMessage(
            "CAR Lookup",
            f"Imovel {cod} carregado (UF: {uf or '?'}, campo: {field_used}). Arquivo salvo em {out_path}",
            level=Qgis.Success,
            duration=6,
        )
