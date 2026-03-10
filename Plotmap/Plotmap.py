#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft Plot Map Generator
Liest Plot-Daten aus einer JSON-Datei und erstellt eine interaktive HTML-Karte
"""

import json
import hashlib
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from copy import deepcopy
import os


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
        else:
            return f"{area:,} m²".replace(',', '.')
    
    def get_price(self) -> int:
        """Berechnet den Kaufpreis (Fläche × 256 €)"""
        return self.get_area_m2() * 256
    
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
        
        # Name kombinieren
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


def uuid_to_color(uuid: str) -> str:
    """Generiert eine konsistente Farbe aus einer UUID"""
    # Hash der UUID erstellen
    hash_obj = hashlib.md5(uuid.encode())
    hash_hex = hash_obj.hexdigest()
    
    # Erste 6 Zeichen als RGB-Farbe verwenden
    # Helligkeit anpassen für bessere Sichtbarkeit
    r = int(hash_hex[0:2], 16)
    g = int(hash_hex[2:4], 16)
    b = int(hash_hex[4:6], 16)
    
    # Farben etwas aufhellen für bessere Sichtbarkeit
    r = min(255, r + 50)
    g = min(255, g + 50)
    b = min(255, b + 50)
    
    return f"#{r:02x}{g:02x}{b:02x}"


def rename_plots_sequential(json_data: dict) -> dict:
    """Benennt Plots sequenziell um, beginnend bei _PLOT_1"""
    world_zones = json_data.get("worldZones", {})
    
    # Sammle alle Plots
    all_plots = []
    for dim_id_str, zone_data in world_zones.items():
        for area in zone_data.get("areaZones", []):
            all_plots.append({
                'area': area,
                'dimension': dim_id_str
            })
    
    # Sortiere nach ID (falls vorhanden)
    all_plots.sort(key=lambda x: x['area'].get('id', 999999))
    
    # Benenne um
    next_number = 1
    for plot_info in all_plots:
        area = plot_info['area']
        old_name = area.get('name', '')
        
        # Nur _PLOT_ Namen umbenennen
        if old_name.startswith('_PLOT_'):
            new_name = f'_PLOT_{next_number}'
            area['name'] = new_name
            print(f"  Umbenannt: {old_name} → {new_name}")
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
            # Plot-ID
            plot_id = area.get("id", 0)
            
            # Plot-Name
            name = area.get("name", "Unknown")
            
            # Anzeigename (bevorzugt fe.economy.plot.data.name)
            group_perms = area.get("groupPermissions", {})
            display_name = None
            for group, perms in group_perms.items():
                if "fe.economy.plot.data.name" in perms:
                    display_name = perms["fe.economy.plot.data.name"]
                    break
            
            if not display_name:
                display_name = name
            
            # Besitzer finden
            owner_uuid = None
            owner_name = "Unknown"
            
            for group, perms in group_perms.items():
                if "fe.internal.plot.owner" in perms:
                    owner_uuid = perms["fe.internal.plot.owner"]
                    break
            
            # Besitzername aus playerPermissions extrahieren
            player_perms = area.get("playerPermissions", {})
            for player_key, perms in player_perms.items():
                if "PLOT_OWNER" in perms.get("fe.internal.player.groups", ""):
                    # Format: (uuid|name)
                    if "|" in player_key:
                        parts = player_key.strip("()").split("|")
                        if len(parts) == 2 and parts[0] == owner_uuid:
                            owner_name = parts[1]
                            break
            
            # Koordinaten
            area_coords = area.get("area", {})
            low = area_coords.get("low", {})
            high = area_coords.get("high", {})
            
            x_min = low.get("x", 0)
            z_min = low.get("z", 0)
            x_max = high.get("x", 0)
            z_max = high.get("z", 0)
            
            if owner_uuid:
                plot = Plot(
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
                )
                plots.append(plot)
    
    return plots


def read_merge_list(filename: str = "grundstücke.txt") -> Set[int]:
    """Liest die Liste der zu mergenden Plot-IDs"""
    if not os.path.exists(filename):
        # Erstelle leere Datei mit Anleitung
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
            # Ignoriere Kommentare und leere Zeilen
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
    
    # Finde die Plots in der JSON
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
    
    # Parse die Plots
    parsed_plots = []
    for plot_info in plots_to_merge:
        area = plot_info['area']
        dimension = int(plot_info['dimension'])
        
        # Besitzer extrahieren
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
        
        # Koordinaten
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
    
    # Prüfe ob alle Plots denselben Besitzer haben
    owners = set(p['plot'].owner_uuid for p in parsed_plots)
    if len(owners) > 1:
        print(f"Fehler: Plots gehören verschiedenen Besitzern: {owners}")
        return json_data
    
    # Prüfe ob alle Plots in derselben Dimension sind
    dimensions = set(p['plot'].dimension for p in parsed_plots)
    if len(dimensions) > 1:
        print(f"Fehler: Plots sind in verschiedenen Dimensionen: {dimensions}")
        return json_data
    
    # Versuche Plots zu mergen
    result_plots = [p['plot'] for p in parsed_plots]
    merged = True
    
    while merged and len(result_plots) > 1:
        merged = False
        for i in range(len(result_plots)):
            for j in range(i + 1, len(result_plots)):
                if result_plots[i].can_merge(result_plots[j]):
                    new_plot = Plot.merge(result_plots[i], result_plots[j])
                    result_plots = [p for k, p in enumerate(result_plots) if k != i and k != j]
                    result_plots.append(new_plot)
                    merged = True
                    print(f"  Zusammengeführt: Plot {parsed_plots[i]['plot'].plot_id} + Plot {parsed_plots[j]['plot'].plot_id}")
                    break
            if merged:
                break
    
    if len(result_plots) > 1:
        print(f"Warnung: Plots können nicht zu einem rechteckigen Grundstück zusammengeführt werden")
        return json_data
    
    # Aktualisiere JSON
    merged_plot = result_plots[0]
    dimension = parsed_plots[0]['dimension']
    
    # Entferne alte Plots (sortiere absteigend nach Index)
    sorted_plots = sorted(parsed_plots, key=lambda x: x['index'], reverse=True)
    for plot_info in sorted_plots:
        del world_zones[dimension]['areaZones'][plot_info['index']]
    
    # Erstelle neuen Plot-Eintrag
    first_area = parsed_plots[0]['area']
    new_area = deepcopy(first_area)
    new_area['name'] = f"_PLOT_MERGED_{merged_plot.plot_id}"
    new_area['area']['low'] = {
        'x': merged_plot.x_min,
        'y': 0,
        'z': merged_plot.z_min
    }
    new_area['area']['high'] = {
        'x': merged_plot.x_max,
        'y': 256,
        'z': merged_plot.z_max
    }
    new_area['id'] = merged_plot.plot_id
    
    # Füge zusammengeführten Plot hinzu
    world_zones[dimension]['areaZones'].append(new_area)
    
    print(f"  Erfolgreich zusammengeführt zu Plot ID {merged_plot.plot_id}")
    print(f"  Neue Koordinaten: X: {merged_plot.x_min} bis {merged_plot.x_max}, Z: {merged_plot.z_min} bis {merged_plot.z_max}")
    print(f"  Fläche: {merged_plot.get_area_formatted()}")
    
    return json_data


def generate_html_map(plots: List[Plot], output_file: str = "plot_map.html"):
    """Generiert eine interaktive HTML-Karte"""
    
    # Dimension-Namen
    dimension_names = {
        -1: "Nether",
        -2147483648: "Mystcraft Profiler",
        0: "Oberwelt",
        1: "Ende"
    }
    
    # Plots nach Dimensionen gruppieren
    plots_by_dimension = {}
    for plot in plots:
        dim = plot.dimension
        if dim not in plots_by_dimension:
            plots_by_dimension[dim] = []
        plots_by_dimension[dim].append(plot)
    
    # JSON-Daten für JavaScript vorbereiten
    js_plots_data = {}
    for dim, dim_plots in plots_by_dimension.items():
        js_plots_data[dim] = []
        for plot in dim_plots:
            js_plots_data[dim].append({
                'name': plot.display_name,
                'owner': plot.owner_name,
                'x_min': plot.x_min,
                'z_min': plot.z_min,
                'x_max': plot.x_max,
                'z_max': plot.z_max,
                'area': plot.get_area_m2(),
                'area_formatted': plot.get_area_formatted(),
                'price': plot.get_price(),
                'color': uuid_to_color(plot.owner_uuid)
            })
    
    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Minecraft Plot Map</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            overflow: hidden;
            background: #1a1a1a;
            color: #fff;
        }}
        
        #controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: rgba(0, 0, 0, 0.8);
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }}
        
        #controls label {{
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
        }}
        
        #controls select {{
            width: 200px;
            padding: 8px;
            border-radius: 4px;
            border: none;
            background: #333;
            color: #fff;
            cursor: pointer;
        }}
        
        #info {{
            position: absolute;
            bottom: 10px;
            left: 10px;
            z-index: 1000;
            background: rgba(0, 0, 0, 0.8);
            padding: 10px 15px;
            border-radius: 8px;
            font-size: 14px;
            min-width: 200px;
        }}
        
        #canvas-container {{
            width: 100vw;
            height: 100vh;
            cursor: grab;
            position: relative;
        }}
        
        #canvas-container.grabbing {{
            cursor: grabbing;
        }}
        
        canvas {{
            display: block;
            background: #0d0d0d;
        }}
        
        #tooltip {{
            position: absolute;
            background: rgba(0, 0, 0, 0.95);
            color: #fff;
            padding: 12px 16px;
            border-radius: 6px;
            pointer-events: none;
            display: none;
            z-index: 2000;
            max-width: 300px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
            border: 1px solid #444;
        }}
        
        #tooltip .plot-name {{
            font-weight: bold;
            font-size: 16px;
            margin-bottom: 8px;
            color: #4CAF50;
        }}
        
        #tooltip .plot-info {{
            font-size: 13px;
            line-height: 1.6;
        }}
        
        #tooltip .plot-info strong {{
            color: #aaa;
        }}
    </style>
</head>
<body>
    <div id="controls">
        <label for="dimension-select">Dimension:</label>
        <select id="dimension-select"></select>
    </div>
    
    <div id="info">
        <div>Zoom: <span id="zoom-level">100%</span></div>
        <div>Maus: Verschieben | Mausrad: Zoom</div>
    </div>
    
    <div id="canvas-container">
        <canvas id="canvas"></canvas>
    </div>
    
    <div id="tooltip"></div>
    
    <script>
        // Plot-Daten
        const plotsData = {json.dumps(js_plots_data)};
        const dimensionNames = {json.dumps(dimension_names)};
        
        // Canvas Setup
        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d');
        const container = document.getElementById('canvas-container');
        const tooltip = document.getElementById('tooltip');
        
        // Viewport-Zustand
        let viewportX = 0;
        let viewportZ = 0;
        let scale = 2;
        let isDragging = false;
        let lastMouseX = 0;
        let lastMouseZ = 0;
        let currentDimension = 0;
        let currentPlots = [];
        
        // Canvas-Größe anpassen
        function resizeCanvas() {{
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
            draw();
        }}
        
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();
        
        // Dimension-Auswahl initialisieren
        function initDimensionSelect() {{
            const select = document.getElementById('dimension-select');
            select.innerHTML = '';
            
            for (const [dim, name] of Object.entries(dimensionNames)) {{
                if (plotsData[dim] && plotsData[dim].length > 0) {{
                    const option = document.createElement('option');
                    option.value = dim;
                    option.textContent = name;
                    select.appendChild(option);
                }}
            }}
            
            select.addEventListener('change', (e) => {{
                currentDimension = parseInt(e.target.value);
                loadDimension();
            }});
            
            // Erste verfügbare Dimension laden
            if (select.options.length > 0) {{
                currentDimension = parseInt(select.options[0].value);
                loadDimension();
            }}
        }}
        
        // Dimension laden
        function loadDimension() {{
            currentPlots = plotsData[currentDimension] || [];
            
            if (currentPlots.length > 0) {{
                // Viewport zentrieren
                centerViewport();
            }}
            
            draw();
        }}
        
        // Viewport auf alle Plots zentrieren
        function centerViewport() {{
            if (currentPlots.length === 0) return;
            
            let minX = Infinity, maxX = -Infinity;
            let minZ = Infinity, maxZ = -Infinity;
            
            for (const plot of currentPlots) {{
                minX = Math.min(minX, plot.x_min);
                maxX = Math.max(maxX, plot.x_max);
                minZ = Math.min(minZ, plot.z_min);
                maxZ = Math.max(maxZ, plot.z_max);
            }}
            
            const centerX = (minX + maxX) / 2;
            const centerZ = (minZ + maxZ) / 2;
            
            viewportX = centerX;
            viewportZ = centerZ;
            
            // Zoom anpassen
            const width = maxX - minX;
            const depth = maxZ - minZ;
            const scaleX = canvas.width / (width * 1.5);
            const scaleZ = canvas.height / (depth * 1.5);
            scale = Math.min(scaleX, scaleZ, 10);
            scale = Math.max(scale, 0.1);
        }}
        
        // Welt- zu Screen-Koordinaten
        function worldToScreen(x, z) {{
            const screenX = canvas.width / 2 + (x - viewportX) * scale;
            const screenZ = canvas.height / 2 + (z - viewportZ) * scale;
            return {{ x: screenX, z: screenZ }};
        }}
        
        // Screen- zu Welt-Koordinaten
        function screenToWorld(screenX, screenZ) {{
            const x = viewportX + (screenX - canvas.width / 2) / scale;
            const z = viewportZ + (screenZ - canvas.height / 2) / scale;
            return {{ x, z }};
        }}
        
        // Zeichnen
        function draw() {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // Gitter zeichnen
            drawGrid();
            
            // Plots zeichnen
            for (const plot of currentPlots) {{
                drawPlot(plot);
            }}
            
            // Zoom-Level aktualisieren
            document.getElementById('zoom-level').textContent = Math.round(scale * 50) + '%';
        }}
        
        // Gitter zeichnen
        function drawGrid() {{
            ctx.strokeStyle = '#222';
            ctx.lineWidth = 1;
            
            const gridSize = 16;
            const worldBounds = {{
                left: viewportX - canvas.width / (2 * scale),
                right: viewportX + canvas.width / (2 * scale),
                top: viewportZ - canvas.height / (2 * scale),
                bottom: viewportZ + canvas.height / (2 * scale)
            }};
            
            // Vertikale Linien
            for (let x = Math.floor(worldBounds.left / gridSize) * gridSize; x <= worldBounds.right; x += gridSize) {{
                const p1 = worldToScreen(x, worldBounds.top);
                const p2 = worldToScreen(x, worldBounds.bottom);
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.z);
                ctx.lineTo(p2.x, p2.z);
                ctx.stroke();
            }}
            
            // Horizontale Linien
            for (let z = Math.floor(worldBounds.top / gridSize) * gridSize; z <= worldBounds.bottom; z += gridSize) {{
                const p1 = worldToScreen(worldBounds.left, z);
                const p2 = worldToScreen(worldBounds.right, z);
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.z);
                ctx.lineTo(p2.x, p2.z);
                ctx.stroke();
            }}
            
            // Ursprung (0,0) hervorheben
            ctx.strokeStyle = '#444';
            ctx.lineWidth = 2;
            const origin = worldToScreen(0, 0);
            ctx.beginPath();
            ctx.moveTo(origin.x - 10, origin.z);
            ctx.lineTo(origin.x + 10, origin.z);
            ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(origin.x, origin.z - 10);
            ctx.lineTo(origin.x, origin.z + 10);
            ctx.stroke();
        }}
        
        // Plot zeichnen
        function drawPlot(plot) {{
            const p1 = worldToScreen(plot.x_min, plot.z_min);
            const p2 = worldToScreen(plot.x_max + 1, plot.z_max + 1);
            
            const width = p2.x - p1.x;
            const height = p2.z - p1.z;
            
            // Plot füllen
            ctx.fillStyle = plot.color + 'CC';
            ctx.fillRect(p1.x, p1.z, width, height);
            
            // Rahmen
            ctx.strokeStyle = plot.color;
            ctx.lineWidth = 2;
            ctx.strokeRect(p1.x, p1.z, width, height);
            
            // Name anzeigen (wenn groß genug)
            if (width > 60 && height > 30) {{
                ctx.fillStyle = '#fff';
                ctx.font = 'bold 12px Arial';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(plot.owner, p1.x + width / 2, p1.z + height / 2);
            }}
        }}
        
        // Plot unter Maus finden
        function getPlotAtPosition(mouseX, mouseZ) {{
            const world = screenToWorld(mouseX, mouseZ);
            
            for (const plot of currentPlots) {{
                if (world.x >= plot.x_min && world.x <= plot.x_max + 1 &&
                    world.z >= plot.z_min && world.z <= plot.z_max + 1) {{
                    return plot;
                }}
            }}
            
            return null;
        }}
        
        // Tooltip anzeigen
        function showTooltip(plot, mouseX, mouseZ) {{
            if (!plot) {{
                tooltip.style.display = 'none';
                return;
            }}
            
            tooltip.innerHTML = `
                <div class="plot-name">${{plot.name}}</div>
                <div class="plot-info">
                    <div><strong>Besitzer:</strong> ${{plot.owner}}</div>
                    <div><strong>Koordinaten:</strong> X: ${{plot.x_min}} bis ${{plot.x_max}}, Z: ${{plot.z_min}} bis ${{plot.z_max}}</div>
                    <div><strong>Fläche:</strong> ${{plot.area_formatted}}</div>
                    <div><strong>Kaufpreis:</strong> ${{plot.price.toLocaleString('de-DE')}} €</div>
                </div>
            `;
            
            tooltip.style.display = 'block';
            tooltip.style.left = mouseX + 15 + 'px';
            tooltip.style.top = mouseZ + 15 + 'px';
            
            // Tooltip nicht außerhalb des Bildschirms
            const rect = tooltip.getBoundingClientRect();
            if (rect.right > window.innerWidth) {{
                tooltip.style.left = mouseX - rect.width - 15 + 'px';
            }}
            if (rect.bottom > window.innerHeight) {{
                tooltip.style.top = mouseZ - rect.height - 15 + 'px';
            }}
        }}
        
        // Event-Handler
        canvas.addEventListener('mousedown', (e) => {{
            isDragging = true;
            lastMouseX = e.clientX;
            lastMouseZ = e.clientY;
            container.classList.add('grabbing');
        }});
        
        canvas.addEventListener('mousemove', (e) => {{
            if (isDragging) {{
                const dx = e.clientX - lastMouseX;
                const dz = e.clientY - lastMouseZ;
                
                viewportX -= dx / scale;
                viewportZ -= dz / scale;
                
                lastMouseX = e.clientX;
                lastMouseZ = e.clientY;
                
                draw();
            }} else {{
                const plot = getPlotAtPosition(e.clientX, e.clientY);
                showTooltip(plot, e.clientX, e.clientY);
            }}
        }});
        
        canvas.addEventListener('mouseup', () => {{
            isDragging = false;
            container.classList.remove('grabbing');
        }});
        
        canvas.addEventListener('mouseleave', () => {{
            isDragging = false;
            container.classList.remove('grabbing');
            tooltip.style.display = 'none';
        }});
        
        canvas.addEventListener('wheel', (e) => {{
            e.preventDefault();
            
            const mouseWorld = screenToWorld(e.clientX, e.clientY);
            
            const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
            scale *= zoomFactor;
            scale = Math.max(0.1, Math.min(scale, 20));
            
            const newMouseWorld = screenToWorld(e.clientX, e.clientY);
            viewportX += mouseWorld.x - newMouseWorld.x;
            viewportZ += mouseWorld.z - newMouseWorld.z;
            
            draw();
        }});
        
        // Initialisierung
        initDimensionSelect();
    </script>
</body>
</html>"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML-Karte erfolgreich erstellt: {output_file}")


def main():
    """Hauptfunktion"""
    import sys
    
    if len(sys.argv) < 2:
        print("Verwendung: python plot_map_generator.py <json_datei> [output.html]")
        sys.exit(1)
    
    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "plot_map.html"
    
    # JSON-Datei laden
    print(f"Lade JSON-Datei: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Plots sequenziell umbenennen
    print("\n=== Sequenzielle Umbenennung ===")
    data = rename_plots_sequential(data)
    
    # Merge-Liste lesen
    print("\n=== Merge-Liste lesen ===")
    merge_ids = read_merge_list("grundstücke.txt")
    
    if merge_ids:
        print(f"Gefunden: {len(merge_ids)} Plot-IDs zum Zusammenführen")
        data = merge_plots_by_ids(data, merge_ids)
        
        # JSON aktualisieren
        print("\nAktualisiere JSON-Datei...")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  JSON-Datei aktualisiert: {json_file}")
        
        # Merge-Liste leeren
        clear_merge_list("grundstücke.txt")
        print("  Merge-Liste geleert")
    else:
        print("Keine Plots zum Zusammenführen gefunden")
    
    # Plots extrahieren
    print("\n=== Plots extrahieren ===")
    plots = parse_plots(data)
    print(f"  → {len(plots)} Plots gefunden")
    
    # HTML-Karte generieren
    print(f"\n=== HTML-Karte generieren ===")
    generate_html_map(plots, output_file)
    
    # Statistiken
    print("\n=== Statistiken ===")
    total_area = sum(plot.get_area_m2() for plot in plots)
    total_price = sum(plot.get_price() for plot in plots)
    
    if total_area > 10000:
        print(f"Gesamtfläche: {total_area / 10000:.2f} ha ({total_area:,} m²)".replace(',', '.'))
    else:
        print(f"Gesamtfläche: {total_area:,} m²".replace(',', '.'))
    
    print(f"Gesamtwert: {total_price:,} €".replace(',', '.'))
    
    # Plots nach Dimension
    by_dim = {}
    for plot in plots:
        by_dim[plot.dimension] = by_dim.get(plot.dimension, 0) + 1
    
    print("\nPlots pro Dimension:")
    for dim, count in sorted(by_dim.items()):
        dim_name = {-1: "Nether", 0: "Oberwelt", 1: "Ende", -2147483648: "Mystcraft"}.get(dim, f"Dimension {dim}")
        print(f"  {dim_name}: {count}")


if __name__ == "__main__":
    main()
