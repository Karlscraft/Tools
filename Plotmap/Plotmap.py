#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Karlscraft – Plotmap-Generator

Liest Plot-Daten aus der ForgeEssentials-JSON und erstellt eine interaktive
HTML-Karte im Karlscraft-Design (Wappenrot / Schrägbalken-Gold / Pergament).

Verwendung:
    python plot_map_generator.py <json_datei> [output.html] [--logo Wappen.png]
"""

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import sys
import urllib.parse
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

SEITENTITEL = "Karlscraft – Plotkarte"
WORTMARKE = "Karlscraft"
UNTERTITEL = "Liegenschaftskarte"
URSPRUNG_LABEL = "Pyramide  0 | 0"

# Wappen wird direkt aus dem Tools-Repository geladen. Damit bleibt die
# HTML-Datei klein und ein ausgetauschtes Logo wirkt sofort auf allen Karten.
WAPPEN_URL = ("https://raw.githubusercontent.com/Karlscraft/Tools/"
              "refs/heads/main/Karlscraft%20Logo.png")
PREIS_PRO_BLOCK = 256  # € je m²

# Georeferenzierung - identisch zum Koordinatenrechner, damit beide Werkzeuge
# denselben Punkt meinen. Nullpunkt ist die Pyramide am Marktplatz, die
# 4°-Drehung laesst die Kaiserstrasse in Minecraft gerade verlaufen.
URSPRUNG_LAT = 49.00923
URSPRUNG_LON = 8.4039
WELT_ROTATION = 4          # Grad; reale Peilung = Minecraft-Winkel + Rotation
GEO_DIMENSION = 0          # nur die Oberwelt liegt ueber dem echten Karlsruhe

# Kachelserver fuer den Stadtplan. tile.openstreetmap.org ist fuer die
# gelegentliche Nutzung eines kleinen Servers zulaessig; bei staerkerer Last
# gehoert hier ein eigener oder gemieteter Kachelserver hin.
OSM_KACHELN = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_MAX_ZOOM = 19
OSM_NACHWEIS = "OpenStreetMap-Mitwirkende"
OSM_NACHWEIS_URL = "https://www.openstreetmap.org/copyright"

# Namensfarben der Amtsträger nach § 4 des Regelwerks. Die Reihenfolge ist die
# Rangfolge: steht ein Spieler in mehreren Gruppen, gilt der erste Treffer.
# "gruppen" listet die Gruppennamen aus der permissions.json. Verglichen wird
# ohne Unterstriche und in Grossbuchstaben, "_ADMIN_" und "admins" treffen also
# beide. Weichen die Namen auf dem Server ab: hier ergaenzen. Das Skript listet
# beim Lauf alle Gruppen auf, die es keinem Amt zuordnen konnte.
AEMTER: List[Dict[str, object]] = [
    {"schluessel": "admin",
     "name": "Administrator",
     "kuerzel": "ADMIN",
     "farbe": "#AA0000",
     "gruppen": ["ADMIN", "ADMINS", "ADMINISTRATOR", "OWNER"]},
    {"schluessel": "operator",
     "name": "Operator",
     "kuerzel": "OP",
     "farbe": "#FFAA00",
     "gruppen": ["OP", "OPS", "OPERATOR", "OPERATORS", "OPERATOREN"]},
    {"schluessel": "moderator",
     "name": "Moderator",
     "kuerzel": "MOD",
     "farbe": "#00AA00",
     "gruppen": ["MOD", "MODS", "MODERATOR", "MODERATORS", "MODERATOREN"]},
]

# Datei fuer manuelle Amtszuweisungen, falls ein Amt nicht ueber die Gruppen
# erkennbar ist (etwa wenn der Administrator nur in der ops.json steht).
AEMTER_DATEI = "aemter.txt"

KOPFZEILEN_LINKS: List[Tuple[str, str]] = [
    ("Tools", "https://karlscraft.github.io/Tools/"),
    ("Regelwerk", "https://github.com/Karlscraft/Regelwerk/wiki"),
    ("Support", "https://github.com/Karlscraft/Support"),
]

DIMENSIONSNAMEN: Dict[int, str] = {
    -1: "Nether",
    -2147483648: "Mystcraft-Profiler",
    0: "Oberwelt",
    1: "Ende",
}

# Wappen als Inline-SVG (Rückfallebene, falls kein Logo übergeben wird)
WAPPEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 72" '
    'role="img" aria-label="Karlscraft-Wappen">'
    '<defs>'
    '<clipPath id="kcSchild">'
    '<path d="M5 4 H59 V37 C59 52 44 64 32 68 C20 64 5 52 5 37 Z"/>'
    '</clipPath>'
    '<linearGradient id="kcRot" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#B8272A"/><stop offset="1" stop-color="#711214"/>'
    '</linearGradient>'
    '<linearGradient id="kcGold" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#F6D765"/><stop offset="0.5" stop-color="#F2C230"/>'
    '<stop offset="1" stop-color="#C9A227"/>'
    '</linearGradient>'
    '</defs>'
    '<g clip-path="url(#kcSchild)">'
    '<rect width="64" height="72" fill="url(#kcRot)"/>'
    '<polygon points="-2,16 14,-2 66,54 50,72" fill="url(#kcGold)"/>'
    '<polygon points="-2,16 14,-2 66,54 50,72" fill="none" '
    'stroke="#8A6B14" stroke-width="1.2" opacity=".5"/>'
    '</g>'
    '<path d="M5 4 H59 V37 C59 52 44 64 32 68 C20 64 5 52 5 37 Z" fill="none" '
    'stroke="url(#kcGold)" stroke-width="3.5" stroke-linejoin="round"/>'
    '<path d="M9 8 H55 V36 C55 49 42 59 32 63 C22 59 9 49 9 36 Z" fill="none" '
    'stroke="#F6D765" stroke-width="0.8" opacity=".55"/>'
    '</svg>'
)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------

@dataclass
class Plot:
    """Repräsentiert ein Minecraft-Grundstück"""
    name: str
    display_name: str
    owner_uuid: str
    owner_name: str
    x_min: int
    z_min: int
    x_max: int
    z_max: int
    dimension: int
    plot_id: int

    def get_area_m2(self) -> int:
        """Berechnet die Fläche in m² (Blöcke sind 1x1m)"""
        # +1 weil Koordinaten Eckpunkte sind, nicht Mittelpunkte
        width = abs(self.x_max - self.x_min) + 1
        depth = abs(self.z_max - self.z_min) + 1
        return width * depth

    def get_area_formatted(self) -> str:
        """Gibt die Fläche formatiert zurück (m² oder ha)"""
        area = self.get_area_m2()
        if area > 10000:
            return f"{area / 10000:.2f} ha"
        return f"{area:,} m²".replace(',', '.')

    def get_price(self) -> int:
        """Berechnet den Kaufpreis (Fläche × Preis pro Block)"""
        return self.get_area_m2() * PREIS_PRO_BLOCK

    def get_bounds(self) -> Tuple[int, int, int, int]:
        """Gibt die Grenzen zurück (x_min, z_min, x_max, z_max)"""
        return (self.x_min, self.z_min, self.x_max, self.z_max)

    def can_merge(self, other: 'Plot') -> bool:
        """Prüft ob zwei Plots zu einem Rechteck zusammengeführt werden können"""
        if self.dimension != other.dimension or self.owner_uuid != other.owner_uuid:
            return False

        x1_min, z1_min, x1_max, z1_max = self.get_bounds()
        x2_min, z2_min, x2_max, z2_max = other.get_bounds()

        # Fall 1: Horizontal angrenzend (gleiche Z-Koordinaten)
        if z1_min == z2_min and z1_max == z2_max:
            if x1_max + 1 == x2_min or x2_max + 1 == x1_min:
                return True

        # Fall 2: Vertikal angrenzend (gleiche X-Koordinaten)
        if x1_min == x2_min and x1_max == x2_max:
            if z1_max + 1 == z2_min or z2_max + 1 == z1_min:
                return True

        return False

    @staticmethod
    def merge(plot1: 'Plot', plot2: 'Plot') -> 'Plot':
        """Führt zwei Plots zu einem zusammen"""
        x_min = min(plot1.x_min, plot2.x_min)
        z_min = min(plot1.z_min, plot2.z_min)
        x_max = max(plot1.x_max, plot2.x_max)
        z_max = max(plot1.z_max, plot2.z_max)

        merged_name = f"{plot1.display_name} + {plot2.display_name}"

        return Plot(
            name=f"MERGED_{plot1.name}_{plot2.name}",
            display_name=merged_name,
            owner_uuid=plot1.owner_uuid,
            owner_name=plot1.owner_name,
            x_min=x_min,
            z_min=z_min,
            x_max=x_max,
            z_max=z_max,
            dimension=plot1.dimension,
            plot_id=plot1.plot_id  # Behalte die erste ID
        )


# ---------------------------------------------------------------------------
# Ämter und Namensfarben
# ---------------------------------------------------------------------------

def _gruppe_normieren(name: str) -> str:
    """Vergleichsform eines Gruppennamens: ohne Unterstriche, in Großbuchstaben"""
    return name.strip().strip("_").upper()


def _kontrastfarbe(hex_farbe: str) -> str:
    """Wählt Schwarz oder Weiß, je nachdem was auf der Farbe besser lesbar ist"""
    r, g, b = (int(hex_farbe[i:i + 2], 16) / 255 for i in (1, 3, 5))
    helligkeit = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#17110F" if helligkeit > 0.5 else "#FFFFFF"


def _spieler_zerlegen(schluessel: str) -> Tuple[str, str]:
    """Zerlegt einen Spielerschluessel der Form "(uuid|Name)" in seine Teile"""
    roh = schluessel.strip().strip("()")
    if "|" in roh:
        uuid, name = roh.split("|", 1)
        return uuid.strip(), name.strip()
    return roh, ""


def sammle_spielergruppen(json_data: dict) -> Dict[Tuple[str, str], Set[str]]:
    """
    Durchsucht die gesamte JSON nach den Gruppen der Spieler.

    ForgeEssentials legt diese je nach Version an unterschiedlichen Stellen ab,
    deshalb wird rekursiv gesucht. Beide gaengigen Schreibweisen werden gelesen:

        "fe.internal.player.groups": "_ADMIN_,_BEWOHNER_"
        "fe.internal.player.group._ADMIN_": "true"
    """
    treffer: Dict[Tuple[str, str], Set[str]] = {}

    def gehe(knoten) -> None:
        if isinstance(knoten, dict):
            for schluessel, wert in knoten.items():
                if schluessel == "playerPermissions" and isinstance(wert, dict):
                    for spieler, rechte in wert.items():
                        if not isinstance(rechte, dict):
                            continue
                        gruppen: Set[str] = set()
                        for recht, inhalt in rechte.items():
                            if recht.startswith("fe.internal.player.group."):
                                gruppen.add(recht.rsplit(".", 1)[-1])
                            elif (recht.startswith("fe.internal.player.group")
                                  and isinstance(inhalt, str)):
                                gruppen.update(
                                    t for t in re.split(r"[,;|\s]+", inhalt) if t)
                        if gruppen:
                            treffer.setdefault(
                                _spieler_zerlegen(spieler), set()).update(gruppen)
                gehe(wert)
        elif isinstance(knoten, list):
            for eintrag in knoten:
                gehe(eintrag)

    gehe(json_data)
    return treffer


def read_aemter_liste(filename: str = AEMTER_DATEI) -> List[Tuple[str, str]]:
    """
    Liest manuelle Amtszuweisungen, falls die Datei vorhanden ist.

    Eine Zuweisung pro Zeile, die Raute beginnt einen Kommentar:

        Alessandro = admin
        Beispielspieler: moderator
    """
    if not os.path.exists(filename):
        return []

    gueltig = {str(a["schluessel"]) for a in AEMTER}
    kuerzel = {str(a["kuerzel"]).lower(): str(a["schluessel"]) for a in AEMTER}
    zuordnung: List[Tuple[str, str]] = []

    with open(filename, 'r', encoding='utf-8') as f:
        for nr, zeile in enumerate(f, 1):
            zeile = zeile.split('#', 1)[0].strip()
            if not zeile:
                continue

            trenner = next((t for t in ('=', ':') if t in zeile), None)
            if not trenner:
                print(f"  Warnung: Zeile {nr} ohne Trennzeichen ignoriert: {zeile}")
                continue

            name, amt = zeile.split(trenner, 1)
            amt = amt.strip().lower()
            amt = kuerzel.get(amt, amt)

            if amt in gueltig:
                zuordnung.append((name.strip(), amt))
            else:
                print(f"  Warnung: Unbekanntes Amt in Zeile {nr}: {amt} "
                      f"(erlaubt: {', '.join(sorted(gueltig))})")

    return zuordnung


def parse_aemter(json_data: dict,
                 manuell: Optional[List[Tuple[str, str]]] = None
                 ) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Ordnet den Spielern ihr Amt zu.

    Rueckgabe:
        zuordnung – UUID und Name (klein geschrieben) zeigen auf den Amtsschluessel
        nach_amt  – Amtsschluessel zeigt auf die Liste der Spielernamen
    """
    rang_je_gruppe: Dict[str, int] = {}
    for rang, amt in enumerate(AEMTER):
        for gruppe in amt["gruppen"]:                      # type: ignore[union-attr]
            rang_je_gruppe[_gruppe_normieren(str(gruppe))] = rang

    zuordnung: Dict[str, str] = {}
    nach_amt: Dict[str, List[str]] = {str(a["schluessel"]): [] for a in AEMTER}
    ohne_zuordnung: Set[str] = set()

    for (uuid, name), gruppen in sammle_spielergruppen(json_data).items():
        bester: Optional[int] = None
        for gruppe in gruppen:
            rang = rang_je_gruppe.get(_gruppe_normieren(gruppe))
            if rang is None:
                ohne_zuordnung.add(gruppe)
            elif bester is None or rang < bester:
                bester = rang

        if bester is None:
            continue

        schluessel = str(AEMTER[bester]["schluessel"])
        if uuid:
            zuordnung[uuid] = schluessel
        if name:
            zuordnung[name.lower()] = schluessel
            nach_amt[schluessel].append(name)

    # Manuelle Zuweisungen haben Vorrang vor den Gruppen
    for name, schluessel in (manuell or []):
        for liste in nach_amt.values():
            liste[:] = [n for n in liste if n.lower() != name.lower()]
        zuordnung[name.lower()] = schluessel
        nach_amt[schluessel].append(name)

    if not any(nach_amt.values()):
        print("  Kein Amtsträger erkannt.")
        if ohne_zuordnung:
            print("  Gefundene Gruppen: " + ", ".join(sorted(ohne_zuordnung)))
            print(f"  Passenden Namen in AEMTER ergänzen oder {AEMTER_DATEI} anlegen "
                  f"(Zeilenformat: Spielername = admin).")
    else:
        for amt in AEMTER:
            namen = nach_amt[str(amt["schluessel"])]
            if namen:
                print(f"  {amt['name']}: {', '.join(sorted(namen))}")

    return zuordnung, nach_amt


def amt_von_plot(plot: Plot, zuordnung: Dict[str, str]) -> Optional[str]:
    """Ermittelt das Amt des Eigentuemers, bevorzugt anhand der UUID"""
    return zuordnung.get(plot.owner_uuid) or zuordnung.get(plot.owner_name.lower())


# ---------------------------------------------------------------------------
# Farbvergabe
# ---------------------------------------------------------------------------

def uuid_to_color(uuid: str) -> str:
    """
    Erzeugt eine konsistente Farbe aus einer UUID.

    Die Farben werden bewusst in Sättigung und Helligkeit begrenzt, damit sie
    auf dem dunklen Kartengrund zum Wappen-Farbklang passen (gedeckte
    Edelsteintöne statt greller Zufallsfarben).
    """
    digest = hashlib.md5(uuid.encode()).hexdigest()

    hue = int(digest[0:4], 16) % 360
    sat = 46 + (int(digest[4:6], 16) % 22)   # 46–67 %
    lig = 48 + (int(digest[6:8], 16) % 12)   # 48–59 %

    # Gelbgrün-Bereich meiden – er kollidiert optisch mit dem Wappengold
    if 62 <= hue <= 88:
        hue = (hue + 40) % 360

    return _hsl_to_hex(hue, sat / 100, lig / 100)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Wandelt HSL (h in Grad, s/l als 0–1) in einen Hex-String um"""
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs(((h / 60) % 2) - 1))
    m = l - c / 2

    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x

    return "#{:02x}{:02x}{:02x}".format(
        round((r + m) * 255), round((g + m) * 255), round((b + m) * 255)
    )


# ---------------------------------------------------------------------------
# JSON-Verarbeitung (unverändert übernommen)
# ---------------------------------------------------------------------------

def rename_plots_sequential(json_data: dict) -> dict:
    """Benennt Plots sequenziell um, beginnend bei _PLOT_1"""
    world_zones = json_data.get("worldZones", {})

    all_plots = []
    for dim_id_str, zone_data in world_zones.items():
        for area in zone_data.get("areaZones", []):
            all_plots.append({'area': area, 'dimension': dim_id_str})

    all_plots.sort(key=lambda x: x['area'].get('id', 999999))

    next_number = 1
    for plot_info in all_plots:
        area = plot_info['area']
        old_name = area.get('name', '')

        if old_name.startswith('_PLOT_'):
            new_name = f'_PLOT_{next_number}'
            area['name'] = new_name
            print(f"  Umbenannt: {old_name} -> {new_name}")
            next_number += 1

    return json_data


def parse_plots(json_data: dict) -> List[Plot]:
    """Extrahiert alle Plots aus den JSON-Daten"""
    plots = []
    world_zones = json_data.get("worldZones", {})

    for dim_id_str, zone_data in world_zones.items():
        dimension = int(dim_id_str)
        area_zones = zone_data.get("areaZones", [])

        for area in area_zones:
            plot_id = area.get("id", 0)
            name = area.get("name", "Unknown")

            group_perms = area.get("groupPermissions", {})
            display_name = None
            for group, perms in group_perms.items():
                if "fe.economy.plot.data.name" in perms:
                    display_name = perms["fe.economy.plot.data.name"]
                    break

            if not display_name:
                display_name = name

            owner_uuid = None
            owner_name = "Unknown"

            for group, perms in group_perms.items():
                if "fe.internal.plot.owner" in perms:
                    owner_uuid = perms["fe.internal.plot.owner"]
                    break

            player_perms = area.get("playerPermissions", {})
            for player_key, perms in player_perms.items():
                if "PLOT_OWNER" in perms.get("fe.internal.player.groups", ""):
                    if "|" in player_key:
                        parts = player_key.strip("()").split("|")
                        if len(parts) == 2 and parts[0] == owner_uuid:
                            owner_name = parts[1]
                            break

            area_coords = area.get("area", {})
            low = area_coords.get("low", {})
            high = area_coords.get("high", {})

            x_min = low.get("x", 0)
            z_min = low.get("z", 0)
            x_max = high.get("x", 0)
            z_max = high.get("z", 0)

            if owner_uuid:
                plots.append(Plot(
                    name=name,
                    display_name=display_name,
                    owner_uuid=owner_uuid,
                    owner_name=owner_name,
                    x_min=x_min,
                    z_min=z_min,
                    x_max=x_max,
                    z_max=z_max,
                    dimension=dimension,
                    plot_id=plot_id
                ))

    return plots


def read_merge_list(filename: str = "grundstücke.txt") -> Set[int]:
    """Liest die Liste der zu mergenden Plot-IDs"""
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Trage hier die IDs der Grundstücke ein, die zusammengeführt werden sollen\n")
            f.write("# Eine ID pro Zeile\n")
            f.write("# Beispiel:\n")
            f.write("# 3\n")
            f.write("# 4\n")
            f.write("# 7\n")
        return set()

    plot_ids = set()
    with open(filename, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                try:
                    plot_ids.add(int(line))
                except ValueError:
                    print(f"Warnung: Ungültige ID ignoriert: {line}")

    return plot_ids


def clear_merge_list(filename: str = "grundstücke.txt"):
    """Leert die Merge-Liste nach erfolgreicher Zusammenführung"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# Trage hier die IDs der Grundstücke ein, die zusammengeführt werden sollen\n")
        f.write("# Eine ID pro Zeile\n")
        f.write("# Beispiel:\n")
        f.write("# 3\n")
        f.write("# 4\n")
        f.write("# 7\n")


def merge_plots_by_ids(json_data: dict, plot_ids: Set[int]) -> dict:
    """Führt Plots mit den angegebenen IDs zusammen"""
    if not plot_ids:
        return json_data

    print(f"\nSuche Plots mit IDs: {sorted(plot_ids)}")

    plots_to_merge = []
    world_zones = json_data.get("worldZones", {})

    for dim_id_str, zone_data in world_zones.items():
        area_zones = zone_data.get("areaZones", [])
        for i, area in enumerate(area_zones):
            if area.get("id") in plot_ids:
                plots_to_merge.append({
                    'dimension': dim_id_str,
                    'index': i,
                    'area': area
                })

    if len(plots_to_merge) < 2:
        print(f"Warnung: Nur {len(plots_to_merge)} Plot(s) gefunden, mindestens 2 benötigt")
        return json_data

    parsed_plots = []
    for plot_info in plots_to_merge:
        area = plot_info['area']
        dimension = int(plot_info['dimension'])

        owner_uuid = None
        owner_name = "Unknown"

        group_perms = area.get("groupPermissions", {})
        for group, perms in group_perms.items():
            if "fe.internal.plot.owner" in perms:
                owner_uuid = perms["fe.internal.plot.owner"]
                break

        player_perms = area.get("playerPermissions", {})
        for player_key, perms in player_perms.items():
            if "PLOT_OWNER" in perms.get("fe.internal.player.groups", ""):
                if "|" in player_key:
                    parts = player_key.strip("()").split("|")
                    if len(parts) == 2 and parts[0] == owner_uuid:
                        owner_name = parts[1]
                        break

        area_coords = area.get("area", {})
        low = area_coords.get("low", {})
        high = area_coords.get("high", {})

        plot = Plot(
            name=area.get("name", "Unknown"),
            display_name=area.get("name", "Unknown"),
            owner_uuid=owner_uuid,
            owner_name=owner_name,
            x_min=low.get("x", 0),
            z_min=low.get("z", 0),
            x_max=high.get("x", 0),
            z_max=high.get("z", 0),
            dimension=dimension,
            plot_id=area.get("id", 0)
        )
        parsed_plots.append({
            'plot': plot,
            'dimension': plot_info['dimension'],
            'index': plot_info['index'],
            'area': area
        })

    owners = set(p['plot'].owner_uuid for p in parsed_plots)
    if len(owners) > 1:
        print(f"Fehler: Plots gehören verschiedenen Besitzern: {owners}")
        return json_data

    dimensions = set(p['plot'].dimension for p in parsed_plots)
    if len(dimensions) > 1:
        print(f"Fehler: Plots sind in verschiedenen Dimensionen: {dimensions}")
        return json_data

    result_plots = [p['plot'] for p in parsed_plots]
    merged = True

    while merged and len(result_plots) > 1:
        merged = False
        for i in range(len(result_plots)):
            for j in range(i + 1, len(result_plots)):
                if result_plots[i].can_merge(result_plots[j]):
                    new_plot = Plot.merge(result_plots[i], result_plots[j])
                    ids = (result_plots[i].plot_id, result_plots[j].plot_id)
                    result_plots = [p for k, p in enumerate(result_plots) if k != i and k != j]
                    result_plots.append(new_plot)
                    merged = True
                    print(f"  Zusammengeführt: Plot {ids[0]} + Plot {ids[1]}")
                    break
            if merged:
                break

    if len(result_plots) > 1:
        print("Warnung: Plots können nicht zu einem rechteckigen Grundstück zusammengeführt werden")
        return json_data

    merged_plot = result_plots[0]
    dimension = parsed_plots[0]['dimension']

    sorted_plots = sorted(parsed_plots, key=lambda x: x['index'], reverse=True)
    for plot_info in sorted_plots:
        del world_zones[dimension]['areaZones'][plot_info['index']]

    first_area = parsed_plots[0]['area']
    new_area = deepcopy(first_area)
    new_area['name'] = f"_PLOT_MERGED_{merged_plot.plot_id}"
    new_area['area']['low'] = {'x': merged_plot.x_min, 'y': 0, 'z': merged_plot.z_min}
    new_area['area']['high'] = {'x': merged_plot.x_max, 'y': 256, 'z': merged_plot.z_max}
    new_area['id'] = merged_plot.plot_id

    world_zones[dimension]['areaZones'].append(new_area)

    print(f"  Erfolgreich zusammengeführt zu Plot ID {merged_plot.plot_id}")
    print(f"  Neue Koordinaten: X: {merged_plot.x_min} bis {merged_plot.x_max}, "
          f"Z: {merged_plot.z_min} bis {merged_plot.z_max}")
    print(f"  Fläche: {merged_plot.get_area_formatted()}")

    return json_data


# ---------------------------------------------------------------------------
# Logo-Einbettung
# ---------------------------------------------------------------------------

def _bildtyp(rohdaten: bytes, dateiname: str) -> str:
    """Ermittelt den MIME-Typ anhand der Dateisignatur (Endung als Rückfall)"""
    if rohdaten.startswith(b'\xff\xd8\xff'):
        return "image/jpeg"
    if rohdaten.startswith(b'\x89PNG\r\n\x1a\n'):
        return "image/png"
    if rohdaten.startswith(b'GIF8'):
        return "image/gif"
    if rohdaten[:4] == b'RIFF' and rohdaten[8:12] == b'WEBP':
        return "image/webp"
    if rohdaten.lstrip()[:5] in (b'<svg ', b'<svg>') or rohdaten.lstrip().startswith(b'<?xml'):
        return "image/svg+xml"
    return mimetypes.guess_type(dateiname)[0] or "image/png"


def build_logo_markup(logo_path: Optional[str] = None,
                      logo_url: Optional[str] = None) -> Tuple[str, str]:
    """
    Liefert (HTML-Markup für das Wappen, Favicon-URL).

    Reihenfolge: --logo schlägt --logo-url, --logo-url schlägt das SVG-Wappen.

    --logo      bettet eine lokale Bilddatei Base64-kodiert ein: die Karte
                bleibt eine einzelne, eigenständige Datei, wird dafür aber
                deutlich größer (bei jedem Serverstopp ein neuer Blob in Git).
    --logo-url  verweist auf das Wappen im Netz. Standard ist WAPPEN_URL, die
                HTML-Datei bleibt damit klein. Mit --logo-url "" abschaltbar.
    Greift keines von beidem, wird das eingebaute SVG-Wappen genutzt.
    """
    if logo_path:
        if not os.path.exists(logo_path):
            print(f"Warnung: Logo nicht gefunden ({logo_path}) – nutze eingebautes Wappen")
        else:
            with open(logo_path, 'rb') as f:
                rohdaten = f.read()
            mime = _bildtyp(rohdaten, logo_path)
            uri = f"data:{mime};base64," + base64.b64encode(rohdaten).decode('ascii')
            markup = f'<img class="kc-wappen" src="{uri}" alt="Karlscraft-Wappen">'
            print(f"  Wappen eingebettet: {logo_path} ({mime}, "
                  f"{len(rohdaten)/1024:.0f} KB -> {len(uri)/1024:.0f} KB Base64)")
            # Als Favicon bleibt das SVG-Wappen: es ist in 16 px schärfer
            # und spart die zweite Kopie der Bilddaten.
            return markup, _svg_favicon()

    if logo_url:
        # Laedt das Bild nicht (Repo offline, Datei umbenannt, kein Netz),
        # springt onerror auf das eingebaute SVG-Wappen um.
        markup = (
            f'<img class="kc-wappen" src="{logo_url}" alt="Karlscraft-Wappen" '
            f'onerror="this.hidden=true;'
            f"document.getElementById('kc-wappen-ersatz').hidden=false\">"
            f'<span class="kc-wappen" id="kc-wappen-ersatz" hidden>{WAPPEN_SVG}</span>'
        )
        return markup, _svg_favicon()

    return f'<span class="kc-wappen">{WAPPEN_SVG}</span>', _svg_favicon()


def _svg_favicon() -> str:
    """Das eingebaute Wappen als Data-URI für das Browser-Symbol"""
    return "data:image/svg+xml," + urllib.parse.quote(WAPPEN_SVG, safe="")


# ---------------------------------------------------------------------------
# HTML-Vorlage
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITEL__</title>
<link rel="icon" href="__FAVICON__">
<style>
:root{
  /* Wappenfarben */
  --rot-tief:#6E1113;
  --rot:#9E1B1E;
  --rot-hell:#B8272A;
  --gold:#C9A227;
  --gold-hell:#F0D97A;
  --balken:#F2C230;
  --tinte:#17110F;
  --pergament:#F4EBDA;

  /* Karte */
  --grund:#141010;
  --karte:#191312;
  --panel:rgba(25,19,18,.94);
  --text:#EFE5D4;
  --text-leise:#B6A48A;

  --serif:Georgia,"Iowan Old Style","Times New Roman",serif;
  --sans:"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --kopf-h:66px;
}

*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{
  font-family:var(--sans);
  background:var(--grund);
  color:var(--text);
  overflow:hidden;
  -webkit-tap-highlight-color:transparent;
}
:focus-visible{outline:2px solid var(--balken);outline-offset:2px}

/* ---------------- Kopfleiste ---------------- */
#kc-kopf{
  position:relative;z-index:30;height:var(--kopf-h);
  display:flex;align-items:center;gap:14px;padding:0 18px;
  background:
    repeating-linear-gradient(118deg,rgba(242,194,48,.10) 0 3px,transparent 3px 26px),
    linear-gradient(180deg,var(--rot) 0%,var(--rot-tief) 100%);
  border-bottom:3px solid var(--gold);
  box-shadow:0 8px 22px rgba(0,0,0,.6);
}
.kc-wappen{display:block;height:44px;width:auto;flex:0 0 auto;
  filter:drop-shadow(0 2px 4px rgba(0,0,0,.55))}
.kc-wappen svg{height:44px;width:auto;display:block}
.kc-wappen[hidden]{display:none}
#kc-titel{display:flex;flex-direction:column;line-height:1.15;min-width:0}
#kc-titel .wortmarke{
  font-family:var(--serif);font-size:23px;font-weight:700;letter-spacing:.05em;
  color:#fff;text-shadow:0 2px 0 rgba(0,0,0,.35)}
#kc-titel .untertitel{
  font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--gold-hell)}
#kc-links{margin-left:auto;display:flex;gap:8px}
#kc-links a{
  font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold-hell);
  text-decoration:none;padding:7px 12px;border:1px solid rgba(242,194,48,.45);
  border-radius:2px;white-space:nowrap;transition:background .15s,color .15s}
#kc-links a:hover{background:var(--balken);color:var(--tinte);border-color:var(--balken)}

/* ---------------- Karte ---------------- */
#kc-karte{position:absolute;top:var(--kopf-h);left:0;right:0;bottom:0;
  cursor:grab;background:var(--karte);touch-action:none}
#kc-karte.zieht{cursor:grabbing}
canvas{display:block}

/* ---------------- Tafeln ---------------- */
.tafel{
  position:absolute;z-index:20;
  background:var(--panel);
  border:1px solid rgba(201,162,39,.5);
  border-radius:3px;
  box-shadow:0 10px 26px rgba(0,0,0,.55),inset 0 0 0 1px rgba(242,194,48,.07);
  backdrop-filter:blur(4px);
}
.tafel h2{
  font-family:var(--serif);font-size:12px;font-weight:700;
  letter-spacing:.18em;text-transform:uppercase;color:var(--gold-hell);
  padding:9px 13px;border-bottom:1px solid rgba(201,162,39,.3);
  background:linear-gradient(180deg,rgba(158,27,30,.5),rgba(158,27,30,0));
  display:flex;align-items:center;justify-content:space-between;gap:10px}
.tafel .inhalt{padding:12px 13px}

#kc-steuerung{top:14px;left:14px;width:224px}
#kc-legende{top:14px;right:14px;width:250px;max-height:calc(100% - 28px);
  display:flex;flex-direction:column}
#kc-legende.versteckt{display:none}
#kc-legende .inhalt{overflow-y:auto;min-height:0;padding:6px 6px 8px}
#anzahl-eigentuemer{font-family:var(--sans);font-size:11px;letter-spacing:0;
  color:var(--text-leise);font-variant-numeric:tabular-nums}
#kc-bilanz{left:14px;bottom:14px;min-width:224px}
#kc-massstab{right:14px;bottom:14px;padding:10px 13px}

label.feld{display:block;font-size:10px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-leise);margin-bottom:6px}
select{
  width:100%;padding:8px 10px;font-family:var(--sans);font-size:14px;
  color:var(--text);background:rgba(0,0,0,.35);
  border:1px solid rgba(201,162,39,.45);border-radius:2px;cursor:pointer}
select:hover{border-color:var(--balken)}
option{background:#1c1513;color:var(--text)}

/* Schalter fuer den Stadtplan */
.schalter{display:flex;align-items:center;gap:9px;margin-top:12px;padding:8px 9px;
  border:1px solid rgba(201,162,39,.35);border-radius:2px;cursor:pointer;
  font-size:13px;transition:background .15s,border-color .15s}
.schalter:hover{background:rgba(242,194,48,.08);border-color:rgba(242,194,48,.6)}
.schalter input{accent-color:var(--balken);width:15px;height:15px;cursor:pointer;flex:0 0 auto}
.schalter.gesperrt{opacity:.42;cursor:not-allowed}
.schalter.gesperrt:hover{background:none;border-color:rgba(201,162,39,.35)}
.schalter .hinweis{display:block;font-size:10px;color:var(--text-leise);margin-top:2px}

/* Kartennachweis - bei aktivem Stadtplan Pflicht */
#kc-nachweis{position:absolute;z-index:20;left:50%;transform:translateX(-50%);
  bottom:14px;display:none;padding:5px 11px;font-size:10.5px;letter-spacing:.02em;
  color:var(--text-leise);background:rgba(20,16,15,.85);
  border:1px solid rgba(201,162,39,.32);border-radius:2px;white-space:nowrap}
#kc-nachweis.an{display:block}
#kc-nachweis a{color:var(--gold-hell);text-decoration:none}
#kc-nachweis a:hover{text-decoration:underline}

.knopfreihe{display:flex;gap:6px;margin-top:12px}
button.knopf{
  flex:1;padding:8px 0;font-family:var(--sans);font-size:13px;font-weight:600;
  color:var(--gold-hell);background:rgba(0,0,0,.3);
  border:1px solid rgba(201,162,39,.45);border-radius:2px;cursor:pointer;
  transition:background .15s,color .15s}
button.knopf:hover{background:var(--balken);color:var(--tinte);border-color:var(--balken)}
button.knopf.breit{flex:2;letter-spacing:.08em}

/* Legende */
.eintrag{display:flex;align-items:center;gap:9px;padding:7px 8px;border-radius:2px;
  cursor:default;transition:background .12s}
.eintrag:hover{background:rgba(242,194,48,.1)}
.eintrag .farbe{width:13px;height:13px;flex:0 0 auto;border-radius:2px;
  border:1px solid rgba(0,0,0,.5);box-shadow:0 0 0 1px rgba(242,194,48,.3)}
.eintrag .wer{flex:1;min-width:0;font-size:13px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.eintrag .amt{flex:0 0 auto;font-size:9px;font-weight:700;letter-spacing:.1em;
  padding:1px 4px;border:1px solid currentColor;border-radius:2px}
.eintrag .zahl{font-size:11px;color:var(--text-leise);font-variant-numeric:tabular-nums}
.leer{padding:14px 10px;font-size:13px;color:var(--text-leise);line-height:1.5}

#amt-legende{flex:0 0 auto;display:flex;flex-wrap:wrap;gap:5px 14px;padding:9px 13px;
  border-top:1px solid rgba(201,162,39,.28);font-size:11px;color:var(--text-leise)}
#amt-legende:empty{display:none}
#amt-legende i{display:inline-block;width:8px;height:8px;border-radius:50%;
  margin-right:6px;vertical-align:0}

/* Bilanz */
.zeile{display:flex;justify-content:space-between;gap:18px;font-size:13px;padding:3px 0}
.zeile dt{color:var(--text-leise)}
.zeile dd{font-variant-numeric:tabular-nums}
.zeile.gesamt{margin-top:7px;padding-top:8px;border-top:1px solid rgba(201,162,39,.28)}
.zeile.gesamt dd{font-family:var(--serif);font-size:15px;color:var(--gold-hell)}

/* Maßstab */
#kc-massstab .balken{height:7px;margin-bottom:6px;
  border:1px solid var(--gold-hell);border-top:none;
  background:repeating-linear-gradient(90deg,var(--gold-hell) 0 8px,transparent 8px 16px)}
#kc-massstab .beschriftung{font-size:11px;color:var(--text-leise);
  letter-spacing:.06em;font-variant-numeric:tabular-nums;white-space:nowrap}

/* ---------------- Grundbuchauszug (Tooltip) ---------------- */
#kc-auszug{
  position:absolute;z-index:40;display:none;pointer-events:none;
  width:290px;background:var(--pergament);color:var(--tinte);
  border:1px solid var(--gold);border-radius:2px;
  box-shadow:0 14px 34px rgba(0,0,0,.6);
  background-image:linear-gradient(180deg,rgba(158,27,30,.05),transparent 90px)}
#kc-auszug .kopf{
  background:linear-gradient(180deg,var(--rot) 0%,var(--rot-tief) 100%);
  border-bottom:2px solid var(--balken);padding:9px 13px}
#kc-auszug .kopf .flur{font-size:10px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--gold-hell)}
#kc-auszug .kopf .name{font-family:var(--serif);font-size:16px;font-weight:700;color:#fff;
  line-height:1.25;word-break:break-word}
#kc-auszug dl{padding:11px 13px 13px;display:grid;grid-template-columns:auto 1fr;
  gap:5px 12px;font-size:12.5px}
#kc-auszug dt{color:#6B5B48;letter-spacing:.03em;white-space:nowrap}
#kc-auszug dd{text-align:right;font-variant-numeric:tabular-nums;word-break:break-word}
#kc-auszug dd.preis{font-family:var(--serif);font-weight:700;font-size:14px;color:var(--rot-tief)}
#kc-auszug .siegel{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:2px;
  font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  vertical-align:1px;box-shadow:0 1px 2px rgba(0,0,0,.3)}

/* ---------------- Mobil ---------------- */
@media (max-width:760px){
  :root{--kopf-h:56px}
  .kc-wappen,.kc-wappen svg{height:34px}
  #kc-titel .wortmarke{font-size:18px}
  #kc-titel .untertitel{font-size:9px;letter-spacing:.16em}
  #kc-links a{padding:6px 8px;font-size:10px}
  #kc-links a:not(:first-child){display:none}
  #kc-steuerung{width:calc(100% - 28px);max-width:300px}
  #kc-legende{top:auto;bottom:14px;right:14px;left:14px;width:auto;max-height:46%}
  /* Geöffnete Legende verdeckt die Bestandstafel – dann blenden wir sie aus */
  #kc-legende:not(.versteckt) ~ #kc-bilanz{display:none}
  #kc-bilanz{font-size:12px}
  #kc-massstab{bottom:14px;right:14px}
  #kc-auszug{width:250px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>

<header id="kc-kopf">
  __LOGO__
  <div id="kc-titel">
    <span class="wortmarke">__WORTMARKE__</span>
    <span class="untertitel">__UNTERTITEL__</span>
  </div>
  <nav id="kc-links">__LINKS__</nav>
</header>

<main id="kc-karte">
  <canvas id="leinwand"></canvas>

  <section class="tafel" id="kc-steuerung">
    <h2>Kartenausschnitt</h2>
    <div class="inhalt">
      <label class="feld" for="dimension">Dimension</label>
      <select id="dimension"></select>
      <div class="knopfreihe">
        <button class="knopf" id="raus" title="Herauszoomen" aria-label="Herauszoomen">&minus;</button>
        <button class="knopf" id="rein" title="Hineinzoomen" aria-label="Hineinzoomen">+</button>
        <button class="knopf breit" id="alles">Alles zeigen</button>
      </div>
      <label class="schalter" id="osm-schalter">
        <input type="checkbox" id="osm">
        <span>Stadtplan hinterlegen
          <span class="hinweis" id="osm-hinweis">OpenStreetMap</span>
        </span>
      </label>
      <div class="knopfreihe">
        <button class="knopf breit" id="legende-schalter" aria-controls="kc-legende" aria-expanded="true">Eigentümer ausblenden</button>
      </div>
    </div>
  </section>

  <section class="tafel" id="kc-legende">
    <h2>Eigentümer <span id="anzahl-eigentuemer"></span></h2>
    <div class="inhalt" id="legende-liste"></div>
    <div id="amt-legende"></div>
  </section>

  <section class="tafel" id="kc-bilanz">
    <h2>Bestand</h2>
    <div class="inhalt">
      <dl>
        <div class="zeile"><dt>Grundstücke</dt><dd id="b-anzahl">–</dd></div>
        <div class="zeile"><dt>Fläche</dt><dd id="b-flaeche">–</dd></div>
        <div class="zeile gesamt"><dt>Verkehrswert</dt><dd id="b-wert">–</dd></div>
      </dl>
    </div>
  </section>

  <div class="tafel" id="kc-massstab">
    <div class="balken" id="massstab-balken"></div>
    <div class="beschriftung" id="massstab-text">–</div>
  </div>

  <div id="kc-nachweis"></div>
  <div id="kc-auszug"></div>
</main>

<script>
"use strict";

const plotsData      = __PLOTS_JSON__;
const dimensionNamen = __DIM_JSON__;
const URSPRUNG_LABEL = __URSPRUNG_JSON__;
const GEO            = __GEO_JSON__;
const aemter         = __AEMTER_JSON__;
const amtsRang       = __AMTSRANG_JSON__;

function amtVon(plot){ return plot.amt ? aemter[plot.amt] : null; }

const leinwand = document.getElementById('leinwand');
const ctx      = leinwand.getContext('2d');
const karte    = document.getElementById('kc-karte');
const auszug   = document.getElementById('kc-auszug');

const nf  = new Intl.NumberFormat('de-DE');
const nf2 = new Intl.NumberFormat('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2});

let viewX = 0, viewZ = 0, scale = 2;
let breite = 0, hoehe = 0, dpr = 1;
let dimension = null;
let plots = [];
let hover = null;
let markiert = null;      // hervorgehobener Eigentümer aus der Legende
let zieht = false, letzteX = 0, letzteY = 0;
let stadtplan = false;                 // Stadtplan hinterlegt?
const kachelCache = new Map();         // "z/x/y" -> Image (oder null bei Fehler)
let zeichenAnfrage = null;

/* ---------- Georeferenzierung ----------
   Uebernommen aus dem Koordinatenrechner, damit beide Werkzeuge denselben
   Punkt meinen: Vincenty "direct" auf dem WGS84-Ellipsoid, reale Peilung ist
   der Minecraft-Winkel zuzueglich der Weltrotation. -------------------- */

const WGS84 = {a: 6378137, b: 6356752.314245, f: 1 / 298.257223563};

function vincentyDirekt(lat1, lon1, peilungGrad, distanz){
  const phi1 = lat1 * Math.PI / 180;
  const lam1 = lon1 * Math.PI / 180;
  const alpha1 = peilungGrad * Math.PI / 180;
  const a = WGS84.a, b = WGS84.b, f = WGS84.f;

  const sinA1 = Math.sin(alpha1), cosA1 = Math.cos(alpha1);
  const tanU1 = (1 - f) * Math.tan(phi1);
  const cosU1 = 1 / Math.sqrt(1 + tanU1 * tanU1);
  const sinU1 = tanU1 * cosU1;

  const sigma1 = Math.atan2(tanU1, cosA1);
  const sinAlpha = cosU1 * sinA1;
  const cosSqAlpha = 1 - sinAlpha * sinAlpha;
  const uSq = cosSqAlpha * (a * a - b * b) / (b * b);
  const A = 1 + uSq / 16384 * (4096 + uSq * (-768 + uSq * (320 - 175 * uSq)));
  const B = uSq / 1024 * (256 + uSq * (-128 + uSq * (74 - 47 * uSq)));

  let sigma = distanz / (b * A), sigmaVor, grenze = 100, cos2SigmaM, sinSigma, cosSigma;
  do {
    cos2SigmaM = Math.cos(2 * sigma1 + sigma);
    sinSigma = Math.sin(sigma);
    cosSigma = Math.cos(sigma);
    const dSigma = B * sinSigma * (cos2SigmaM + B / 4 * (cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM) -
                   B / 6 * cos2SigmaM * (-3 + 4 * sinSigma * sinSigma) * (-3 + 4 * cos2SigmaM * cos2SigmaM)));
    sigmaVor = sigma;
    sigma = distanz / (b * A) + dSigma;
  } while (Math.abs(sigma - sigmaVor) > 1e-12 && --grenze > 0);

  if(grenze === 0) return null;

  const tmp = sinU1 * sinSigma - cosU1 * cosSigma * cosA1;
  const phi2 = Math.atan2(sinU1 * cosSigma + cosU1 * sinSigma * cosA1,
                          (1 - f) * Math.sqrt(sinAlpha * sinAlpha + tmp * tmp));
  const lam = Math.atan2(sinSigma * sinA1, cosU1 * cosSigma - sinU1 * sinSigma * cosA1);
  const C = f / 16 * cosSqAlpha * (4 + f * (4 - 3 * cosSqAlpha));
  const L = lam - (1 - C) * f * sinAlpha *
            (sigma + C * sinSigma * (cos2SigmaM + C * cosSigma * (-1 + 2 * cos2SigmaM * cos2SigmaM)));
  const lam2 = ((lam1 + L + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;

  return {lat: phi2 * 180 / Math.PI, lon: lam2 * 180 / Math.PI};
}

function mcZuLatLon(mcX, mcZ){
  const distanz = Math.sqrt(mcX * mcX + mcZ * mcZ);
  if(distanz === 0) return {lat: GEO.lat, lon: GEO.lon};
  const winkel = Math.atan2(mcX, -mcZ) * 180 / Math.PI;
  const peilung = (winkel + GEO.rotation + 360) % 360;
  return vincentyDirekt(GEO.lat, GEO.lon, peilung, distanz) || {lat: GEO.lat, lon: GEO.lon};
}

// Weltkoordinate in Mercator-Pixel der gewaehlten Kachelstufe
function mercator(punkt, stufe){
  const n = 256 * Math.pow(2, stufe);
  const s = Math.sin(punkt.lat * Math.PI / 180);
  return {
    x: (punkt.lon + 180) / 360 * n,
    y: (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n
  };
}

function mercatorAusMc(x, z, stufe){ return mercator(mcZuLatLon(x, z), stufe); }

/* ---------- Hilfsfunktionen ---------- */

function flaecheText(m2){
  return m2 > 10000 ? nf2.format(m2/10000) + ' ha' : nf.format(m2) + ' m²';
}

function hexZuRgba(hex, alpha){
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}

function anfordern(){
  if(zeichenAnfrage) return;
  zeichenAnfrage = requestAnimationFrame(() => { zeichenAnfrage = null; zeichnen(); });
}

/* ---------- Größe & Koordinaten ---------- */

function groesseAnpassen(){
  const r = karte.getBoundingClientRect();
  breite = r.width; hoehe = r.height;
  dpr = window.devicePixelRatio || 1;
  leinwand.width  = Math.round(breite * dpr);
  leinwand.height = Math.round(hoehe  * dpr);
  leinwand.style.width  = breite + 'px';
  leinwand.style.height = hoehe  + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  zeichnen();
}
window.addEventListener('resize', groesseAnpassen);

function zuBild(x, z){
  return { x: breite/2 + (x - viewX)*scale, y: hoehe/2 + (z - viewZ)*scale };
}
function zuWelt(px, py){
  return { x: viewX + (px - breite/2)/scale, z: viewZ + (py - hoehe/2)/scale };
}
function mausPos(e){
  const r = leinwand.getBoundingClientRect();
  return { x: e.clientX - r.left, y: e.clientY - r.top };
}

/* ---------- Dimensionen ---------- */

function dimensionenAufbauen(){
  const auswahl = document.getElementById('dimension');
  auswahl.innerHTML = '';

  const ids = Object.keys(plotsData)
    .filter(id => plotsData[id] && plotsData[id].length)
    .sort((a,b) => plotsData[b].length - plotsData[a].length);

  if(!ids.length){
    const opt = document.createElement('option');
    opt.textContent = 'Keine Grundstücke vorhanden';
    auswahl.appendChild(opt);
    auswahl.disabled = true;
    plots = [];
    legendeAufbauen();
    bilanzAktualisieren();
    zeichnen();
    return;
  }

  for(const id of ids){
    const opt = document.createElement('option');
    opt.value = id;
    const name = dimensionNamen[id] || ('Dimension ' + id);
    opt.textContent = name + ' (' + plotsData[id].length + ')';
    auswahl.appendChild(opt);
  }

  auswahl.addEventListener('change', e => { dimension = e.target.value; dimensionLaden(); });
  dimension = ids[0];
  dimensionLaden();
}

function dimensionLaden(){
  plots = plotsData[dimension] || [];
  markiert = null;
  hover = null;
  auszug.style.display = 'none';
  alleszeigen();
  legendeAufbauen();
  bilanzAktualisieren();
  osmVerfuegbarkeit();
}

function alleszeigen(){
  if(!plots.length){ viewX = 0; viewZ = 0; scale = 1; anfordern(); return; }

  let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
  for(const p of plots){
    minX = Math.min(minX, p.x_min); maxX = Math.max(maxX, p.x_max + 1);
    minZ = Math.min(minZ, p.z_min); maxZ = Math.max(maxZ, p.z_max + 1);
  }
  viewX = (minX + maxX)/2;
  viewZ = (minZ + maxZ)/2;

  const b = Math.max(maxX - minX, 32), t = Math.max(maxZ - minZ, 32);
  scale = Math.min(breite/(b*1.35), hoehe/(t*1.35), 8);
  scale = Math.max(scale, 0.002);
  anfordern();
}

/* ---------- Zeichnen ---------- */

function gitterSchritt(){
  const stufen = [1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768];
  for(const s of stufen){ if(s*scale >= 55) return s; }
  return 65536;
}

/* ---------- Stadtplan ---------- */

function georeferenziert(){ return dimension === String(GEO.dimension); }

// Kachelstufe so waehlen, dass eine Kachelpixel ungefaehr einem Bildschirm-
// pixel entspricht: Meter je Kachelpixel = 156543,03 * cos(Breite) / 2^Stufe.
function kachelStufe(){
  const breitengrad = Math.cos(GEO.lat * Math.PI / 180);
  const stufe = Math.log2(156543.03392 * breitengrad * scale);
  return Math.max(0, Math.min(GEO.maxZoom, Math.round(stufe)));
}

function kachelHolen(stufe, kx, ky){
  const schluessel = stufe + '/' + kx + '/' + ky;
  if(kachelCache.has(schluessel)) return kachelCache.get(schluessel);

  const bild = new Image();
  kachelCache.set(schluessel, bild);
  bild.onload  = () => anfordern();
  bild.onerror = () => kachelCache.set(schluessel, null);
  bild.src = GEO.kacheln
    .replace('{z}', stufe).replace('{x}', kx).replace('{y}', ky);

  // Cache begrenzen, damit lange Sitzungen den Speicher nicht volllaufen lassen
  if(kachelCache.size > 400){
    const aeltester = kachelCache.keys().next().value;
    kachelCache.delete(aeltester);
  }
  return bild;
}

// Minecraft- und Mercator-Raster stehen um die Weltrotation verdreht
// zueinander. Statt jede Kachel einzeln zu drehen, wird die Umrechnung um die
// Bildmitte linearisiert und als Transformationsmatrix an die Leinwand gegeben.
function kachelnZeichnen(){
  const stufe = kachelStufe();
  const d = 256;  // Stuetzweite der Naeherung in Bloecken

  const m0 = mercatorAusMc(viewX, viewZ, stufe);
  const mx = mercatorAusMc(viewX + d, viewZ, stufe);
  const mz = mercatorAusMc(viewX, viewZ + d, stufe);

  const j11 = (mx.x - m0.x) / d, j12 = (mz.x - m0.x) / d;
  const j21 = (mx.y - m0.y) / d, j22 = (mz.y - m0.y) / d;
  const det = j11 * j22 - j12 * j21;
  if(!det || !isFinite(det)) return;

  // Kehrmatrix: Mercator-Pixel -> Bloecke, anschliessend auf Bildschirm skaliert
  const a =  scale * ( j22 / det), c = scale * (-j12 / det);
  const b =  scale * (-j21 / det), dd = scale * ( j11 / det);
  const e = breite / 2 - (a * m0.x + c * m0.y);
  const f = hoehe  / 2 - (b * m0.x + dd * m0.y);

  // Sichtbaren Bereich in Kachelnummern umrechnen
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for(const [ex, ey] of [[0,0],[breite,0],[0,hoehe],[breite,hoehe]]){
    const welt = zuWelt(ex, ey);
    const m = mercatorAusMc(welt.x, welt.z, stufe);
    minX = Math.min(minX, m.x); maxX = Math.max(maxX, m.x);
    minY = Math.min(minY, m.y); maxY = Math.max(maxY, m.y);
  }

  const grenze = Math.pow(2, stufe);
  const von = { x: Math.floor(minX / 256) - 1, y: Math.floor(minY / 256) - 1 };
  const bis = { x: Math.floor(maxX / 256) + 1, y: Math.floor(maxY / 256) + 1 };
  if((bis.x - von.x + 1) * (bis.y - von.y + 1) > 240) return;  // Notbremse

  ctx.save();
  ctx.transform(a, b, c, dd, e, f);
  ctx.imageSmoothingQuality = 'high';
  // Kacheln in den dunklen Kartenklang einpassen
  ctx.filter = 'grayscale(.45) brightness(.72) contrast(1.05)';

  for(let ky = von.y; ky <= bis.y; ky++){
    if(ky < 0 || ky >= grenze) continue;
    for(let kx = von.x; kx <= bis.x; kx++){
      const kachel = kachelHolen(stufe, ((kx % grenze) + grenze) % grenze, ky);
      if(kachel && kachel.complete && kachel.naturalWidth){
        // halbes Pixel Ueberlappung gegen Fugen zwischen den Kacheln
        ctx.drawImage(kachel, kx * 256, ky * 256, 256.5, 256.5);
      }
    }
  }
  ctx.restore();
}

function zeichnen(){
  ctx.clearRect(0, 0, breite, hoehe);
  const plan = stadtplan && georeferenziert();
  if(plan) kachelnZeichnen();
  gitterZeichnen(plan);
  for(const p of plots) plotZeichnen(p);
  ursprungZeichnen();
  massstabAktualisieren();
}

function gitterZeichnen(gedaempft){
  const d = gedaempft ? .45 : 1;   // ueber dem Stadtplan tritt das Raster zurueck
  const schritt = gitterSchritt();
  const grob    = schritt * 4;
  const links = viewX - breite/(2*scale),  rechts = viewX + breite/(2*scale);
  const oben  = viewZ - hoehe /(2*scale),  unten  = viewZ + hoehe /(2*scale);

  function linien(s, farbe, staerke){
    ctx.strokeStyle = farbe; ctx.lineWidth = staerke;
    ctx.beginPath();
    for(let x = Math.floor(links/s)*s; x <= rechts; x += s){
      const px = Math.round(zuBild(x, 0).x) + .5;
      ctx.moveTo(px, 0); ctx.lineTo(px, hoehe);
    }
    for(let z = Math.floor(oben/s)*s; z <= unten; z += s){
      const py = Math.round(zuBild(0, z).y) + .5;
      ctx.moveTo(0, py); ctx.lineTo(breite, py);
    }
    ctx.stroke();
  }

  linien(schritt, 'rgba(201,162,39,' + (.07 * d) + ')', 1);
  linien(grob,    'rgba(201,162,39,' + (.16 * d) + ')', 1);

  // Hauptachsen durch den Nullpunkt
  ctx.strokeStyle = 'rgba(242,194,48,' + (.32 * d) + ')'; ctx.lineWidth = 1;
  ctx.beginPath();
  const o = zuBild(0, 0);
  ctx.moveTo(Math.round(o.x)+.5, 0); ctx.lineTo(Math.round(o.x)+.5, hoehe);
  ctx.moveTo(0, Math.round(o.y)+.5); ctx.lineTo(breite, Math.round(o.y)+.5);
  ctx.stroke();
}

function ursprungZeichnen(){
  const o = zuBild(0, 0);
  if(o.x < -60 || o.x > breite+60 || o.y < -40 || o.y > hoehe+40) return;

  ctx.save();
  ctx.strokeStyle = '#F2C230'; ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(o.x-9, o.y); ctx.lineTo(o.x+9, o.y);
  ctx.moveTo(o.x, o.y-9); ctx.lineTo(o.x, o.y+9);
  ctx.stroke();
  ctx.beginPath(); ctx.arc(o.x, o.y, 4.5, 0, Math.PI*2);
  ctx.strokeStyle = 'rgba(242,194,48,.75)'; ctx.lineWidth = 1.5; ctx.stroke();

  ctx.font = '11px Georgia, serif';
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.fillStyle = 'rgba(0,0,0,.65)';
  const w = ctx.measureText(URSPRUNG_LABEL).width;
  ctx.fillRect(o.x + 12, o.y - 9, w + 10, 18);
  ctx.fillStyle = '#F0D97A';
  ctx.fillText(URSPRUNG_LABEL, o.x + 17, o.y + 1);
  ctx.restore();
}

function plotZeichnen(p){
  const a = zuBild(p.x_min, p.z_min);
  const b = zuBild(p.x_max + 1, p.z_max + 1);
  const w = Math.max(b.x - a.x, 2), h = Math.max(b.y - a.y, 2);
  if(a.x > breite || a.y > hoehe || b.x < 0 || b.y < 0) return;

  const gedimmt = markiert && p.owner !== markiert;
  const aktiv   = hover === p;

  ctx.save();
  if(gedimmt) ctx.globalAlpha = .22;

  const plan = stadtplan && georeferenziert();
  ctx.fillStyle = hexZuRgba(p.color, aktiv ? (plan ? .68 : .78) : (plan ? .40 : .55));
  ctx.fillRect(a.x, a.y, w, h);

  ctx.strokeStyle = aktiv ? '#F2C230' : p.color;
  ctx.lineWidth   = aktiv ? 2.5 : 1.5;
  ctx.strokeRect(a.x + .5, a.y + .5, w - 1, h - 1);

  if(w > 54 && h > 20){
    ctx.save();
    ctx.beginPath(); ctx.rect(a.x, a.y, w, h); ctx.clip();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';

    // Dunkle Kontur statt Schlagschatten: haelt auch die gesaettigten
    // Amtsfarben auf hellen Grundstuecksflaechen lesbar.
    const amt = amtVon(p);
    const zweizeilig = h > 40 && w > 90;
    const mx = a.x + w/2, my = a.y + h/2;

    ctx.font = '600 12px "Segoe UI", Arial, sans-serif';
    ctx.strokeStyle = 'rgba(0,0,0,.9)'; ctx.lineWidth = 3;
    ctx.strokeText(p.owner, mx, my - (zweizeilig ? 8 : 0));
    ctx.fillStyle = amt ? amt.farbe : '#fff';
    ctx.fillText(p.owner, mx, my - (zweizeilig ? 8 : 0));

    if(zweizeilig){
      ctx.font = '11px Georgia, serif';
      ctx.strokeStyle = 'rgba(0,0,0,.85)'; ctx.lineWidth = 3;
      ctx.strokeText(p.name, mx, my + 9);
      ctx.fillStyle = 'rgba(240,217,122,.92)';
      ctx.fillText(p.name, mx, my + 9);
    }
    ctx.restore();
  }
  ctx.restore();
}

function massstabAktualisieren(){
  const stufen = [1,2,5,10,25,50,100,250,500,1000,2500,5000,10000,25000,50000];
  let bloecke = stufen[stufen.length-1];
  for(const s of stufen){ if(s*scale >= 90){ bloecke = s; break; } }
  document.getElementById('massstab-balken').style.width = Math.round(bloecke*scale) + 'px';
  document.getElementById('massstab-text').textContent = nf.format(bloecke) + ' Blöcke · ' + nf.format(bloecke) + ' m';
}

/* ---------- Legende & Bilanz ---------- */

function legendeAufbauen(){
  const liste = document.getElementById('legende-liste');
  liste.innerHTML = '';

  const nachEigentuemer = new Map();
  for(const p of plots){
    const e = nachEigentuemer.get(p.owner)
           || {owner:p.owner, color:p.color, amt:p.amt, anzahl:0, flaeche:0};
    e.anzahl++; e.flaeche += p.area;
    nachEigentuemer.set(p.owner, e);
  }
  const alle = [...nachEigentuemer.values()].sort((a,b) => b.flaeche - a.flaeche);
  document.getElementById('anzahl-eigentuemer').textContent = alle.length ? alle.length : '';

  if(!alle.length){
    liste.innerHTML = '<p class="leer">In dieser Dimension ist noch kein Grundstück vergeben.</p>';
    return;
  }

  for(const e of alle){
    const amt = e.amt ? aemter[e.amt] : null;
    const zeile = document.createElement('div');
    zeile.className = 'eintrag';
    zeile.title = amt ? e.owner + ' – ' + amt.name : e.owner;
    zeile.innerHTML =
      '<span class="farbe" style="background:' + e.color +
        (amt ? ';box-shadow:0 0 0 2px ' + amt.farbe : '') + '"></span>' +
      '<span class="wer"' + (amt ? ' style="color:' + amt.farbe + '"' : '') + '></span>' +
      (amt ? '<span class="amt" style="color:' + amt.farbe + '">' + amt.kuerzel + '</span>' : '') +
      '<span class="zahl">' + e.anzahl + '× · ' + flaecheText(e.flaeche) + '</span>';
    zeile.querySelector('.wer').textContent = e.owner;
    zeile.addEventListener('mouseenter', () => { markiert = e.owner; anfordern(); });
    zeile.addEventListener('mouseleave', () => { markiert = null;    anfordern(); });
    liste.appendChild(zeile);
  }

  amtsLegendeAufbauen(alle);
}

// Erklaert die Namensfarben - aber nur fuer Aemter, die hier auch vorkommen
function amtsLegendeAufbauen(eintraege){
  const fuss = document.getElementById('amt-legende');
  const vorhanden = amtsRang.filter(schluessel => eintraege.some(e => e.amt === schluessel));

  fuss.innerHTML = vorhanden.map(schluessel => {
    const amt = aemter[schluessel];
    return '<span><i style="background:' + amt.farbe + '"></i>' + amt.name + '</span>';
  }).join('');
}

function bilanzAktualisieren(){
  const flaeche = plots.reduce((s,p) => s + p.area, 0);
  const wert    = plots.reduce((s,p) => s + p.price, 0);
  document.getElementById('b-anzahl').textContent  = nf.format(plots.length);
  document.getElementById('b-flaeche').textContent = flaecheText(flaeche);
  document.getElementById('b-wert').textContent    = nf.format(wert) + ' €';
}

/* ---------- Grundbuchauszug ---------- */

function plotAn(px, py){
  const w = zuWelt(px, py);
  for(let i = plots.length - 1; i >= 0; i--){
    const p = plots[i];
    if(w.x >= p.x_min && w.x <= p.x_max + 1 && w.z >= p.z_min && w.z <= p.z_max + 1) return p;
  }
  return null;
}

// Auf dem hellen Pergament traegt ein gefuelltes Siegel die Amtsfarbe besser
// als farbige Schrift - besonders beim Orange der Operatoren.
function amtsSiegel(p){
  const amt = amtVon(p);
  if(!amt) return '';
  return '<span class="siegel" style="background:' + amt.farbe +
         ';color:' + amt.kontrast + '">' + amt.name + '</span>';
}

function auszugZeigen(p, px, py){
  if(!p){ auszug.style.display = 'none'; return; }

  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  auszug.innerHTML =
    '<div class="kopf">' +
      '<div class="flur">Flurstück ' + esc(p.id) + '</div>' +
      '<div class="name">' + esc(p.name) + '</div>' +
    '</div>' +
    '<dl>' +
      '<dt>Eigentümer</dt><dd>' + esc(p.owner) + amtsSiegel(p) + '</dd>' +
      '<dt>Lage X</dt><dd>' + nf.format(p.x_min) + ' bis ' + nf.format(p.x_max) + '</dd>' +
      '<dt>Lage Z</dt><dd>' + nf.format(p.z_min) + ' bis ' + nf.format(p.z_max) + '</dd>' +
      '<dt>Fläche</dt><dd>' + flaecheText(p.area) + '</dd>' +
      '<dt>Kaufpreis</dt><dd class="preis">' + nf.format(p.price) + ' €</dd>' +
    '</dl>';

  auszug.style.display = 'block';
  const r = auszug.getBoundingClientRect();
  let x = px + 18, y = py + 18;
  if(x + r.width  > breite) x = px - r.width  - 18;
  if(y + r.height > hoehe ) y = Math.max(8, py - r.height - 18);
  auszug.style.left = x + 'px';
  auszug.style.top  = y + 'px';
}

/* ---------- Maus ---------- */

leinwand.addEventListener('mousedown', e => {
  zieht = true; letzteX = e.clientX; letzteY = e.clientY;
  karte.classList.add('zieht');
  auszug.style.display = 'none';
});

leinwand.addEventListener('mousemove', e => {
  if(zieht){
    viewX -= (e.clientX - letzteX)/scale;
    viewZ -= (e.clientY - letzteY)/scale;
    letzteX = e.clientX; letzteY = e.clientY;
    anfordern();
  } else {
    const m = mausPos(e);
    const p = plotAn(m.x, m.y);
    if(p !== hover){ hover = p; anfordern(); }
    auszugZeigen(p, m.x, m.y);
  }
});

window.addEventListener('mouseup', () => { zieht = false; karte.classList.remove('zieht'); });

leinwand.addEventListener('mouseleave', () => {
  zieht = false; karte.classList.remove('zieht');
  auszug.style.display = 'none';
  if(hover){ hover = null; anfordern(); }
});

leinwand.addEventListener('wheel', e => {
  e.preventDefault();
  const m = mausPos(e);
  zoomen(e.deltaY < 0 ? 1.12 : 1/1.12, m.x, m.y);
}, {passive:false});

function zoomen(faktor, px, py){
  if(px === undefined){ px = breite/2; py = hoehe/2; }
  const vorher = zuWelt(px, py);
  scale = Math.max(0.002, Math.min(scale * faktor, 24));
  const nachher = zuWelt(px, py);
  viewX += vorher.x - nachher.x;
  viewZ += vorher.z - nachher.z;
  anfordern();
}

/* ---------- Touch ---------- */

let touchAbstand = 0;

leinwand.addEventListener('touchstart', e => {
  auszug.style.display = 'none';
  if(e.touches.length === 1){
    letzteX = e.touches[0].clientX; letzteY = e.touches[0].clientY;
  } else if(e.touches.length === 2){
    touchAbstand = abstand(e.touches);
  }
}, {passive:false});

leinwand.addEventListener('touchmove', e => {
  e.preventDefault();
  if(e.touches.length === 1){
    viewX -= (e.touches[0].clientX - letzteX)/scale;
    viewZ -= (e.touches[0].clientY - letzteY)/scale;
    letzteX = e.touches[0].clientX; letzteY = e.touches[0].clientY;
    anfordern();
  } else if(e.touches.length === 2 && touchAbstand){
    const neu = abstand(e.touches);
    const m   = mitte(e.touches);
    zoomen(neu/touchAbstand, m.x, m.y);
    touchAbstand = neu;
  }
}, {passive:false});

leinwand.addEventListener('touchend', e => {
  if(e.touches.length < 2) touchAbstand = 0;
  if(e.touches.length === 1){
    letzteX = e.touches[0].clientX; letzteY = e.touches[0].clientY;
  }
  // Tippen zeigt den Grundbuchauszug
  if(e.changedTouches.length === 1 && !e.touches.length){
    const r = leinwand.getBoundingClientRect();
    const px = e.changedTouches[0].clientX - r.left;
    const py = e.changedTouches[0].clientY - r.top;
    const p = plotAn(px, py);
    hover = p; anfordern();
    auszugZeigen(p, px, py);
  }
});

function abstand(t){
  return Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
}
function mitte(t){
  const r = leinwand.getBoundingClientRect();
  return { x:(t[0].clientX + t[1].clientX)/2 - r.left, y:(t[0].clientY + t[1].clientY)/2 - r.top };
}

/* ---------- Bedienelemente ---------- */

/* ---------- Stadtplan schalten ---------- */

const osmFeld     = document.getElementById('osm');
const osmSchalter = document.getElementById('osm-schalter');
const osmHinweis  = document.getElementById('osm-hinweis');
const nachweis    = document.getElementById('kc-nachweis');

nachweis.innerHTML = 'Kartengrundlage: <a href="' + GEO.nachweisUrl +
  '" target="_blank" rel="noopener">&copy; ' + GEO.nachweis + '</a>';

osmFeld.addEventListener('change', () => {
  stadtplan = osmFeld.checked;
  nachweisAktualisieren();
  anfordern();
});

function nachweisAktualisieren(){
  nachweis.classList.toggle('an', stadtplan && georeferenziert());
}

// Nur die Oberwelt liegt ueber dem echten Karlsruhe - in anderen Dimensionen
// waere ein Stadtplan sinnlos, der Schalter wird dort gesperrt.
function osmVerfuegbarkeit(){
  const moeglich = georeferenziert();
  osmFeld.disabled = !moeglich;
  osmSchalter.classList.toggle('gesperrt', !moeglich);
  osmHinweis.textContent = moeglich
    ? 'OpenStreetMap'
    : 'Nur in der Oberwelt verfügbar';
  nachweisAktualisieren();
}

document.getElementById('rein').addEventListener('click',  () => zoomen(1.35));
document.getElementById('raus').addEventListener('click',  () => zoomen(1/1.35));
document.getElementById('alles').addEventListener('click', alleszeigen);
const legende  = document.getElementById('kc-legende');
const schalter = document.getElementById('legende-schalter');

function legendeSetzen(sichtbar){
  legende.classList.toggle('versteckt', !sichtbar);
  schalter.textContent = sichtbar ? 'Eigentümer ausblenden' : 'Eigentümer anzeigen';
  schalter.setAttribute('aria-expanded', String(sichtbar));
}
schalter.addEventListener('click', () => legendeSetzen(legende.classList.contains('versteckt')));

// Auf schmalen Bildschirmen startet die Legende eingeklappt
legendeSetzen(!window.matchMedia('(max-width:760px)').matches);

/* ---------- Start ---------- */

groesseAnpassen();
dimensionenAufbauen();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTML-Erzeugung
# ---------------------------------------------------------------------------

def generate_html_map(plots: List[Plot],
                      output_file: str = "plot_map.html",
                      logo_path: Optional[str] = None,
                      logo_url: Optional[str] = None,
                      aemter_zuordnung: Optional[Dict[str, str]] = None):
    """Generiert die interaktive HTML-Karte im Karlscraft-Design"""

    plots_by_dimension: Dict[str, List[dict]] = {}
    for plot in plots:
        plots_by_dimension.setdefault(str(plot.dimension), []).append({
            'id': plot.plot_id,
            'name': plot.display_name,
            'owner': plot.owner_name,
            'x_min': plot.x_min,
            'z_min': plot.z_min,
            'x_max': plot.x_max,
            'z_max': plot.z_max,
            'area': plot.get_area_m2(),
            'price': plot.get_price(),
            'color': uuid_to_color(plot.owner_uuid),
            'amt': amt_von_plot(plot, aemter_zuordnung or {}),
        })

    dim_namen = {str(k): v for k, v in DIMENSIONSNAMEN.items()}

    # Amtsdaten fuer die Anzeige: Farbe, Kuerzel und die Schriftfarbe, die auf
    # der Amtsfarbe lesbar bleibt (fuer das Siegel im Grundbuchauszug).
    amtsdaten = {
        str(amt["schluessel"]): {
            "name": amt["name"],
            "kuerzel": amt["kuerzel"],
            "farbe": amt["farbe"],
            "kontrast": _kontrastfarbe(str(amt["farbe"])),
        }
        for amt in AEMTER
    }
    amtsrang = [str(amt["schluessel"]) for amt in AEMTER]

    geo = {
        "lat": URSPRUNG_LAT,
        "lon": URSPRUNG_LON,
        "rotation": WELT_ROTATION,
        "dimension": GEO_DIMENSION,
        "kacheln": OSM_KACHELN,
        "maxZoom": OSM_MAX_ZOOM,
        "nachweis": OSM_NACHWEIS,
        "nachweisUrl": OSM_NACHWEIS_URL,
    }
    logo_markup, favicon = build_logo_markup(logo_path, logo_url)

    links = "".join(
        f'<a href="{url}" target="_blank" rel="noopener">{text}</a>'
        for text, url in KOPFZEILEN_LINKS
    )

    def js(value) -> str:
        # </ maskieren, damit der Datenblock das <script>-Element nicht beendet
        return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")

    html = (HTML_TEMPLATE
            .replace("__TITEL__", SEITENTITEL)
            .replace("__FAVICON__", favicon)
            .replace("__LOGO__", logo_markup)
            .replace("__WORTMARKE__", WORTMARKE)
            .replace("__UNTERTITEL__", UNTERTITEL)
            .replace("__LINKS__", links)
            .replace("__PLOTS_JSON__", js(plots_by_dimension))
            .replace("__DIM_JSON__", js(dim_namen))
            .replace("__URSPRUNG_JSON__", js(URSPRUNG_LABEL))
            .replace("__AEMTER_JSON__", js(amtsdaten))
            .replace("__AMTSRANG_JSON__", js(amtsrang))
            .replace("__GEO_JSON__", js(geo)))

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"HTML-Karte erfolgreich erstellt: {output_file}")


# ---------------------------------------------------------------------------
# Konsolenausgabe
# ---------------------------------------------------------------------------

def konsole_vorbereiten() -> None:
    """
    Macht die Konsolenausgabe gegen Kodierungsfehler unempfindlich.

    Wird die Ausgabe umgeleitet (z. B. `python Plotmap.py ... 2>&1 | Tee-Object`),
    schreibt Python unter Windows nicht in der Konsolen-Codepage, sondern in
    cp1252. Zeichen ausserhalb dieses Zeichensatzes brechen den Lauf dann mit
    einem UnicodeEncodeError ab - mitten in der Kartenerzeugung.

    errors="replace" ersetzt solche Zeichen durch "?", statt abzubrechen.
    Die Kodierung selbst bleibt unangetastet, damit Umlaute im PowerShell-Log
    weiterhin richtig ankommen. line_buffering sorgt dafuer, dass der Fortschritt
    auch in einer Pipe sofort sichtbar wird und nicht blockweise nachrueckt.
    """
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(errors="replace", line_buffering=True)
        except (AttributeError, ValueError, OSError):
            pass  # z. B. bereits geschlossen oder kein TextIOWrapper


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main():
    konsole_vorbereiten()

    parser = argparse.ArgumentParser(
        description="Erstellt die Karlscraft-Plotkarte aus der ForgeEssentials-JSON."
    )
    parser.add_argument("json_datei", help="Pfad zur ForgeEssentials-JSON")
    parser.add_argument("output", nargs="?", default="plot_map.html",
                        help="Zieldatei (Standard: plot_map.html)")
    parser.add_argument("--logo", default=None,
                        help="Pfad zum Karlscraft-Wappen (PNG/JPG/SVG). "
                             "Wird Base64-kodiert in die HTML-Datei eingebettet.")
    parser.add_argument("--logo-url", default=WAPPEN_URL,
                        help="URL des Wappens (Standard: Tools-Repository). "
                             'Mit --logo-url "" wird das eingebaute SVG-Wappen genutzt.')
    parser.add_argument("--merge-liste", default="grundstücke.txt",
                        help="Datei mit den zusammenzuführenden Plot-IDs")
    parser.add_argument("--aemter-liste", default=AEMTER_DATEI,
                        help="Datei mit manuellen Amtszuweisungen "
                             "(Zeilenformat: Spielername = admin)")
    args = parser.parse_args()

    print(f"Lade JSON-Datei: {args.json_datei}")
    with open(args.json_datei, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print("\n=== Sequenzielle Umbenennung ===")
    data = rename_plots_sequential(data)

    print("\n=== Merge-Liste lesen ===")
    merge_ids = read_merge_list(args.merge_liste)

    if merge_ids:
        print(f"Gefunden: {len(merge_ids)} Plot-IDs zum Zusammenführen")
        data = merge_plots_by_ids(data, merge_ids)

        print("\nAktualisiere JSON-Datei...")
        with open(args.json_datei, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  JSON-Datei aktualisiert: {args.json_datei}")

        clear_merge_list(args.merge_liste)
        print("  Merge-Liste geleert")
    else:
        print("Keine Plots zum Zusammenführen gefunden")

    print("\n=== Plots extrahieren ===")
    plots = parse_plots(data)
    print(f"  -> {len(plots)} Plots gefunden")

    print("\n=== Ämter ===")
    aemter_zuordnung, _ = parse_aemter(data, read_aemter_liste(args.aemter_liste))

    print("\n=== HTML-Karte generieren ===")
    generate_html_map(plots, args.output, args.logo, args.logo_url, aemter_zuordnung)

    print("\n=== Statistiken ===")
    total_area = sum(plot.get_area_m2() for plot in plots)
    total_price = sum(plot.get_price() for plot in plots)

    if total_area > 10000:
        print(f"Gesamtfläche: {total_area / 10000:.2f} ha ({total_area:,} m²)".replace(',', '.'))
    else:
        print(f"Gesamtfläche: {total_area:,} m²".replace(',', '.'))

    print(f"Gesamtwert: {total_price:,} €".replace(',', '.'))

    by_dim: Dict[int, int] = {}
    for plot in plots:
        by_dim[plot.dimension] = by_dim.get(plot.dimension, 0) + 1

    print("\nPlots pro Dimension:")
    for dim, count in sorted(by_dim.items()):
        dim_name = DIMENSIONSNAMEN.get(dim, f"Dimension {dim}")
        print(f"  {dim_name}: {count}")


if __name__ == "__main__":
    main()
