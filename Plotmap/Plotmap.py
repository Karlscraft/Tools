#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft Plot Map Generator
Liest Plot-Daten aus einer JSON-Datei, bereinigt die Daten,
führt Plots zusammen und erstellt eine interaktive HTML-Karte
"""

import json
import hashlib
import re
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from copy import deepcopy


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
    original_area_data: dict  # Original area dict für JSON-Updates
    
    def get_area_m2(self) -> int:
        """Berechnet die Fläche in m² (Blöcke sind 1x1m)"""
        # +1 weil Koordinaten Eckpunkte sind, nicht Mittelpunkte
        width = abs(self.x_max - self.x_min) + 1
        depth = abs(self.z_max - self.z_min) + 1
        return width * depth
    
    def get_area_display(self) -> str:
        """Gibt die Fläche formatiert zurück (m² oder ha)"""
        area = self.get_area_m2()
        if area > 10000:
            ha = area / 10000
            return f"{ha:.2f} ㏊"
        else:
            return f"{area:,} ㎡".replace(',', '.')
    
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
        
        # Display-Name kombinieren wenn beide custom names haben
        if plot1.display_name.startswith("_PLOT_") and plot2.display_name.startswith("_PLOT_"):
            merged_display_name = f"_MERGED_PLOT_"
        elif not plot1.display_name.startswith("_PLOT_"):
            merged_display_name = plot1.display_name
        elif not plot2.display_name.startswith("_PLOT_"):
            merged_display_name = plot2.display_name
        else:
            merged_display_name = f"{plot1.display_name} + {plot2.display_name}"
        
        # Merged area data erstellen
        merged_area = deepcopy(plot1.original_area_data)
        merged_area['area']['low']['x'] = x_min
        merged_area['area']['low']['z'] = z_min
        merged_area['area']['high']['x'] = x_max
        merged_area['area']['high']['z'] = z_max
        
        return Plot(
            name=plot1.name,  # Behalte den ersten Namen
            display_name=merged_display_name,
            owner_uuid=plot1.owner_uuid,
            owner_name=plot1.owner_name,
            x_min=x_min,
            z_min=z_min,
            x_max=x_max,
            z_max=z_max,
            dimension=plot1.dimension,
            original_area_data=merged_area
        )


def uuid_to_color(uuid: str) -> str:
    """Generiert eine konsistente Farbe aus einer UUID"""
    hash_obj = hashlib.md5(uuid.encode())
    hash_hex = hash_obj.hexdigest()
    
    # Erste 6 Zeichen als RGB-Farbe verwenden
    r = int(hash_hex[0:2], 16)
    g = int(hash_hex[2:4], 16)
    b = int(hash_hex[4:6], 16)
    
    # Farben etwas aufhellen für bessere Sichtbarkeit
    r = min(255, r + 50)
    g = min(255, g + 50)
    b = min(255, b + 50)
    
    return f"#{r:02x}{g:02x}{b:02x}"


def extract_plot_number(name: str) -> Optional[int]:
    """Extrahiert die Plot-Nummer aus einem Namen wie _PLOT_4"""
    match = re.match(r'_PLOT_(\d+)', name)
    if match:
        return int(match.group(1))
    return None


def renumber_plots(json_data: dict) -> Tuple[dict, int]:
    """
    Nummeriert Plots neu, sodass sie bei _PLOT_1 beginnen und durchgehend sind.
    Gibt die modifizierte JSON-Struktur und die Anzahl umbenannter Plots zurück.
    """
    data = deepcopy(json_data)
    renamed_count = 0
    
    world_zones = data.get("worldZones", {})
    
    # Sammle alle existierenden Plot-Nummern
    existing_numbers = set()
    plot_areas = []
    
    for dim_id_str, zone_data in world_zones.items():
        area_zones = zone_data.get("areaZones", [])
        for area in area_zones:
            name = area.get("name", "")
            plot_num = extract_plot_number(name)
            if plot_num is not None:
                existing_numbers.add(plot_num)
                plot_areas.append((dim_id_str, area))
    
    # Prüfe ob Umnummerierung nötig ist
    if not existing_numbers:
        return data, 0
    
    expected_numbers = set(range(1, len(existing_numbers) + 1))
    if existing_numbers == expected_numbers:
        print("  → Plot-Nummerierung ist bereits korrekt")
        return data, 0
    
    # Erstelle Mapping: alte Nummer -> neue Nummer
    sorted_old_numbers = sorted(existing_numbers)
    number_mapping = {}
    next_new_number = 1
    
    for old_num in sorted_old_numbers:
        number_mapping[old_num] = next_new_number
        next_new_number += 1
    
    # Benenne Plots um
    for dim_id_str, area in plot_areas:
        old_name = area.get("name", "")
        old_num = extract_plot_number(old_name)
        
        if old_num is not None and old_num in number_mapping:
            new_num = number_mapping[old_num]
            if old_num != new_num:
                new_name = f"_PLOT_{new_num}"
                area["name"] = new_name
                renamed_count += 1
                print(f"  → Umbenannt: {old_name} -> {new_name}")
    
    return data, renamed_count


def parse_plots(json_data: dict) -> List[Plot]:
    """Extrahiert alle Plots aus den JSON-Daten"""
    plots = []
    
    world_zones = json_data.get("worldZones", {})
    
    for dim_id_str, zone_data in world_zones.items():
        dimension = int(dim_id_str)
        area_zones = zone_data.get("areaZones", [])
        
        for area in area_zones:
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
                    original_area_data=area
                )
                plots.append(plot)
    
    return plots


def merge_adjacent_plots(plots: List[Plot]) -> Tuple[List[Plot], List[str]]:
    """
    Führt angrenzende Plots desselben Besitzers zusammen.
    Gibt die zusammengeführten Plots und eine Liste der entfernten Plot-Namen zurück.
    """
    if not plots:
        return plots, []
    
    merged = True
    result = plots[:]
    removed_names = []
    
    while merged:
        merged = False
        new_result = []
        used = set()
        
        for i, plot1 in enumerate(result):
            if i in used:
                continue
            
            # Versuche plot1 mit anderen Plots zu mergen
            merged_plot = plot1
            for j, plot2 in enumerate(result):
                if i >= j or j in used:
                    continue
                
                if merged_plot.can_merge(plot2):
                    merged_plot = Plot.merge(merged_plot, plot2)
                    removed_names.append(plot2.name)
                    used.add(j)
                    merged = True
            
            new_result.append(merged_plot)
            used.add(i)
        
        result = new_result
    
    return result, removed_names


def update_json_with_merged_plots(json_data: dict, merged_plots: List[Plot], removed_names: List[str]) -> dict:
    """
    Aktualisiert die JSON-Daten mit den zusammengeführten Plots.
    Entfernt die alten Plots und fügt die zusammengeführten ein.
    """
    data = deepcopy(json_data)
    world_zones = data.get("worldZones", {})
    
    # Entferne die Plots die zusammengeführt wurden
    for dim_id_str, zone_data in world_zones.items():
        area_zones = zone_data.get("areaZones", [])
        zone_data["areaZones"] = [
            area for area in area_zones 
            if area.get("name") not in removed_names
        ]
    
    # Aktualisiere die Koordinaten der zusammengeführten Plots
    for plot in merged_plots:
        dim_id_str = str(plot.dimension)
        if dim_id_str in world_zones:
            area_zones = world_zones[dim_id_str].get("areaZones", [])
            for area in area_zones:
                if area.get("name") == plot.name:
                    # Update coordinates
                    area["area"]["low"]["x"] = plot.x_min
                    area["area"]["low"]["z"] = plot.z_min
                    area["area"]["high"]["x"] = plot.x_max
                    area["area"]["high"]["z"] = plot.z_max
                    break
    
    return data


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
                'area_m2': plot.get_area_m2(),
                'area_display': plot.get_area_display(),
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
                    <div><strong>Fläche:</strong> ${{plot.area_display}}</div>
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
    
    print(f"✓ HTML-Karte erfolgreich erstellt: {output_file}")


def main():
    """Hauptfunktion"""
    import sys
    
    if len(sys.argv) < 2:
        print("Verwendung: python plot_map_generator.py <json_datei> [output.html]")
        print("\nDas Skript wird:")
        print("  1. Plot-Namen neu nummerieren (_PLOT_1, _PLOT_2, ...)")
        print("  2. Angrenzende Plots desselben Besitzers zusammenführen")
        print("  3. Die JSON-Datei mit den Änderungen überschreiben")
        print("  4. Eine interaktive HTML-Karte erstellen")
        sys.exit(1)
    
    json_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "plot_map.html"
    
    print("=" * 70)
    print("MINECRAFT PLOT MAP GENERATOR")
    print("=" * 70)
    
    # JSON-Datei laden
    print(f"\n[1/5] Lade JSON-Datei: {json_file}")
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("✓ JSON-Datei geladen")
    
    # Plots neu nummerieren
    print(f"\n[2/5] Nummeriere Plots neu...")
    data, renamed_count = renumber_plots(data)
    if renamed_count > 0:
        print(f"✓ {renamed_count} Plot(s) wurden umbenannt")
    
    # Plots extrahieren
    print(f"\n[3/5] Extrahiere Plots...")
    plots = parse_plots(data)
    print(f"✓ {len(plots)} Plot(s) gefunden")
    
    # Plots zusammenführen
    print(f"\n[4/5] Führe angrenzende Plots zusammen...")
    original_count = len(plots)
    merged_plots, removed_names = merge_adjacent_plots(plots)
    merged_count = original_count - len(merged_plots)
    
    if merged_count > 0:
        print(f"✓ {merged_count} Plot(s) wurden zusammengeführt")
        print(f"✓ {len(merged_plots)} Plot(s) nach Zusammenführung")
        
        # JSON aktualisieren
        data = update_json_with_merged_plots(data, merged_plots, removed_names)
    else:
        print("✓ Keine angrenzenden Plots zum Zusammenführen gefunden")
    
    # JSON-Datei überschreiben wenn Änderungen vorgenommen wurden
    if renamed_count > 0 or merged_count > 0:
        print(f"\n[5/5] Überschreibe JSON-Datei mit Änderungen...")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ JSON-Datei aktualisiert: {json_file}")
    else:
        print(f"\n[5/5] Keine Änderungen - JSON-Datei bleibt unverändert")
    
    # HTML-Karte generieren
    print(f"\n[6/6] Generiere HTML-Karte...")
    generate_html_map(merged_plots, output_file)
    
    # Statistiken
    print("\n" + "=" * 70)
    print("STATISTIKEN")
    print("=" * 70)
    total_area = sum(plot.get_area_m2() for plot in merged_plots)
    total_price = sum(plot.get_price() for plot in merged_plots)
    
    if total_area > 10000:
        print(f"Gesamtfläche: {total_area / 10000:.2f} ㏊ ({total_area:,} ㎡)".replace(',', '.'))
    else:
        print(f"Gesamtfläche: {total_area:,} ㎡".replace(',', '.'))
    
    print(f"Gesamtwert: {total_price:,} €".replace(',', '.'))
    
    # Plots nach Dimension
    by_dim = {}
    for plot in merged_plots:
        by_dim[plot.dimension] = by_dim.get(plot.dimension, 0) + 1
    
    print("\nPlots pro Dimension:")
    dimension_names = {-1: "Nether", 0: "Oberwelt", 1: "Ende", -2147483648: "Mystcraft"}
    for dim, count in sorted(by_dim.items()):
        dim_name = dimension_names.get(dim, f"Dimension {dim}")
        print(f"  {dim_name}: {count}")
    
    # Besitzer-Statistiken
    by_owner = {}
    for plot in merged_plots:
        owner = plot.owner_name
        if owner not in by_owner:
            by_owner[owner] = {'count': 0, 'area': 0}
        by_owner[owner]['count'] += 1
        by_owner[owner]['area'] += plot.get_area_m2()
    
    print("\nPlots pro Besitzer:")
    for owner, stats in sorted(by_owner.items(), key=lambda x: x[1]['area'], reverse=True):
        area = stats['area']
        if area > 10000:
            area_str = f"{area / 10000:.2f} ㏊"
        else:
            area_str = f"{area:,} ㎡".replace(',', '.')
        print(f"  {owner}: {stats['count']} Plot(s), {area_str}")
    
    print("\n" + "=" * 70)
    print("✓ FERTIG!")
    print("=" * 70)


if __name__ == "__main__":
    main()
