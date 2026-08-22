"""Generates crisp SVG and rasterized PNG of the young, reckless 'Son of Anton' silhouette."""
import os
from pathlib import Path

svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <radialGradient id="bgGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#1e1808"/>
      <stop offset="100%" stop-color="#090b10"/>
    </radialGradient>
    <linearGradient id="amberGlow" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fbbf24"/>
      <stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#000000" flood-opacity="0.6"/>
    </filter>
  </defs>

  <!-- Dark Mode Squircle Base -->
  <rect width="512" height="512" rx="115" fill="url(#bgGlow)"/>
  <rect width="510" height="510" x="1" y="1" rx="114" fill="none" stroke="rgba(245, 158, 11, 0.25)" stroke-width="2"/>

  <!-- Son of Anton Silhouette (Younger, Reckless, Messy Hair, Tilted Shades) -->
  <g filter="url(#shadow)" transform="translate(0, 8)">
    <!-- Shoulders & Upper Body (Slightly tilted, loose jacket collar) -->
    <path d="M 120 480 C 130 410, 165 375, 205 355 C 220 370, 292 370, 307 355 C 347 375, 382 410, 392 480 Z" fill="#ffffff"/>
    
    <!-- Neck & Jawline (Sharper, youthful angular jaw) -->
    <path d="M 215 360 L 210 295 C 210 295, 230 335, 256 335 C 282 335, 302 295, 302 295 L 297 360 Z" fill="#ffffff"/>
    
    <!-- Head Base / Face Stencil -->
    <path d="M 190 220 C 190 285, 220 330, 256 330 C 292 330, 322 285, 322 220 C 322 170, 292 135, 256 135 C 220 135, 190 170, 190 220 Z" fill="#ffffff"/>

    <!-- Messy, Reckless Youthful Hair (Wild swept strands, textured fringe & spikes) -->
    <path d="
      M 160 215
      C 150 160, 175 110, 220 85
      C 235 50, 275 55, 295 75
      C 325 50, 365 75, 360 115
      C 385 130, 380 175, 365 210
      C 375 175, 355 145, 335 140
      C 320 110, 280 100, 250 115
      C 230 95, 195 105, 185 135
      C 170 150, 165 180, 160 215 Z
      M 210 130 Q 230 175, 215 205 Q 240 170, 255 180 Q 270 155, 300 175 Q 315 150, 330 185 Q 345 155, 320 130 Z
    " fill="#ffffff"/>

    <!-- Reckless Tilted Sunglasses / Cyber Shades (Sharp angular geometry) -->
    <!-- Left Lens (Tilted slightly down-left for smug/reckless expression) -->
    <polygon points="195,225 242,228 238,262 198,256" fill="#090b10"/>
    <!-- Right Lens (Slightly higher angled) -->
    <polygon points="270,230 317,222 313,253 274,260" fill="#090b10"/>
    <!-- Bridge & Temples -->
    <line x1="240" y1="229" x2="272" y2="230" stroke="#090b10" stroke-width="5" stroke-linecap="round"/>
    <line x1="185" y1="224" x2="197" y2="226" stroke="#090b10" stroke-width="4"/>
    <line x1="315" y1="223" x2="327" y2="220" stroke="#090b10" stroke-width="4"/>

    <!-- Amber Cyber Glint in Right Lens (Ludicrous Overdrive spark) -->
    <polygon points="280,236 295,233 292,242 278,245" fill="url(#amberGlow)" opacity="0.95"/>

    <!-- Smug Asymmetrical Smile Line (Minimalist Stencil Cutout) -->
    <path d="M 248 296 Q 266 298, 276 290" fill="none" stroke="#090b10" stroke-width="4" stroke-linecap="round"/>
  </g>
</svg>
"""

svg_path = str(Path(__file__).resolve().parents[1] / "assets" / "logos" / "son_of_anton_logo.svg")
with open(svg_path, "w", encoding="utf-8") as f:
    f.write(svg_content.strip())

print(f"Generated Son of Anton SVG: {svg_path}")
