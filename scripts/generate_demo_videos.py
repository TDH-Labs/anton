import os
import sys
import subprocess
import math
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
FPS = 30

# Fonts
FONT_TITLE = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 28)
FONT_SUB = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 20)
FONT_BODY = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 16)
FONT_MONO = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 15)
FONT_MONO_SM = ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 12)
FONT_CAPTION = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 24)

# Colors
BG_MAIN = (12, 14, 18)
BG_CANVAS = (16, 18, 24)
BG_CARD = (24, 27, 36)
BORDER_COLOR = (45, 50, 65)
TEXT_MAIN = (248, 250, 252)
TEXT_MUTED = (148, 163, 184)
TEXT_DIM = (100, 116, 139)
COLOR_CYAN = (56, 189, 248)
COLOR_EMERALD = (16, 185, 129)
COLOR_AMBER = (245, 158, 11)
COLOR_PURPLE = (168, 85, 247)
COLOR_RED = (239, 68, 68)

def create_base_frame(son_of_anton=False, active_tab="studio"):
    img = Image.new('RGB', (WIDTH, HEIGHT), color=BG_MAIN)
    d = ImageDraw.Draw(img)
    
    # macOS window header bar
    d.rectangle([0, 0, WIDTH, 50], fill=(20, 23, 30))
    d.line([(0, 50), (WIDTH, 50)], fill=BORDER_COLOR, width=1)
    
    # macOS window buttons
    d.ellipse([20, 18, 34, 32], fill=(239, 68, 68))
    d.ellipse([42, 18, 56, 32], fill=(245, 158, 11))
    d.ellipse([64, 18, 78, 32], fill=(16, 185, 129))
    
    # App Title in Header
    d.text((WIDTH//2 - 120, 14), "ANTON — Autonomous Studio v1.0", fill=TEXT_MUTED, font=FONT_BODY)
    
    # Header Nav
    d.rectangle([40, 70, WIDTH - 40, 130], fill=(20, 23, 32), outline=BORDER_COLOR, width=1)
    
    # Brand
    d.rounded_rectangle([55, 80, 95, 120], radius=8, fill=(30, 35, 48), outline=(60, 68, 90))
    d.text((67, 88), "⚡", fill=COLOR_CYAN, font=FONT_TITLE)
    d.text((110, 85), "ANTON", fill=TEXT_MAIN, font=FONT_TITLE)
    d.text((110, 112), "Autonomous OS", fill=TEXT_DIM, font=FONT_MONO_SM)
    
    # Son of Anton Toggle in Header
    son_bg = (50, 35, 10) if son_of_anton else (25, 28, 38)
    son_border = COLOR_AMBER if son_of_anton else BORDER_COLOR
    son_text = "⚡ SON OF ANTON [ACTIVE]" if son_of_anton else "⚡ SON OF ANTON [OFF]"
    son_color = COLOR_AMBER if son_of_anton else TEXT_MUTED
    
    d.rounded_rectangle([WIDTH - 380, 85, WIDTH - 160, 115], radius=15, fill=son_bg, outline=son_border, width=1)
    d.ellipse([WIDTH - 368, 95, WIDTH - 356, 105], fill=son_color)
    d.text((WIDTH - 345, 92), son_text, fill=son_color, font=FONT_MONO_SM)
    
    # Daemon status
    d.rounded_rectangle([WIDTH - 140, 85, WIDTH - 55, 115], radius=15, fill=(16, 40, 30), outline=(16, 185, 129))
    d.text((WIDTH - 125, 92), "ONLINE", fill=COLOR_EMERALD, font=FONT_MONO_SM)
    
    # Main Tabs
    tabs = ["📐 Studio Canvas", "🌌 3D Second Brain", "📊 Telemetry & Ledger", "⚙️ Key Vault"]
    tx = 40
    for t in tabs:
        active = (active_tab == "studio" and "Studio" in t) or (active_tab == "neural" and "Brain" in t)
        t_bg = (35, 40, 55) if active else (18, 21, 28)
        t_border = (80, 90, 120) if active else BORDER_COLOR
        t_color = TEXT_MAIN if active else TEXT_MUTED
        d.rounded_rectangle([tx, 145, tx + 180, 180], radius=8, fill=t_bg, outline=t_border, width=1)
        d.text((tx + 15, 153), t, fill=t_color, font=FONT_BODY)
        tx += 195
        
    return img

def draw_dot_grid(d, x1, y1, x2, y2, step=30):
    for x in range(x1 + 15, x2, step):
        for y in range(y1 + 15, y2, step):
            d.ellipse([x, y, x+2, y+2], fill=(40, 45, 60))

def draw_card_node(d, x, y, w, h, tag, title, desc, tag_color, active_glow=False, status_badge=None):
    outline = tag_color if active_glow else BORDER_COLOR
    fill = (28, 32, 44) if active_glow else BG_CARD
    d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=fill, outline=outline, width=2 if active_glow else 1)
    
    # Tag
    d.rounded_rectangle([x + 12, y + 12, x + 12 + len(tag)*8 + 14, y + 30], radius=5, fill=(tag_color[0]//4, tag_color[1]//4, tag_color[2]//4))
    d.text((x + 18, y + 14), tag.upper(), fill=tag_color, font=FONT_MONO_SM)
    
    if status_badge:
        d.text((x + w - len(status_badge)*8 - 14, y + 14), status_badge, fill=tag_color, font=FONT_MONO_SM)
        
    d.text((x + 12, y + 42), title, fill=TEXT_MAIN, font=FONT_BODY)
    d.text((x + 12, y + 68), desc, fill=TEXT_DIM, font=FONT_MONO_SM)

def draw_bezier_wire(d, x1, y1, x2, y2, color=BORDER_COLOR, pulse=False):
    pts = []
    for t in range(0, 101, 5):
        prog = t / 100.0
        # cubic bezier
        cx1 = x1 + (x2 - x1) * 0.5
        cy1 = y1
        cx2 = x1 + (x2 - x1) * 0.5
        cy2 = y2
        bx = (1-prog)**3 * x1 + 3*(1-prog)**2 * prog * cx1 + 3*(1-prog) * prog**2 * cx2 + prog**3 * x2
        by = (1-prog)**3 * y1 + 3*(1-prog)**2 * prog * cy1 + 3*(1-prog) * prog**2 * cy2 + prog**3 * y2
        pts.append((bx, by))
    for i in range(len(pts)-1):
        d.line([pts[i], pts[i+1]], fill=color if not pulse else COLOR_CYAN, width=3 if pulse else 2)

def render_video_1():
    """Demo 1: Visual Reconciliation Workflow Creation & Gate Execution"""
    out_path = '/Users/ai/rooms/devops/assets/demos/anton_demo_1_reconciliation_workflow.mp4'
    proc = subprocess.Popen([
        '/opt/homebrew/bin/ffmpeg', '-y', '-f', 'image2pipe', '-vcodec', 'png',
        '-r', str(FPS), '-i', '-', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', out_path
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    total_frames = 12 * FPS
    prompt_text = "Build daily 3-way reconciliation between Stripe and QuickBooks with $0.00 hard gate"
    
    for f in range(total_frames):
        t = f / FPS
        img = create_base_frame(son_of_anton=False)
        d = ImageDraw.Draw(img)
        
        # 3 Column Layout
        # Left Pane: Navigator
        d.rounded_rectangle([40, 195, 320, HEIGHT - 110], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((60, 215), "KNOWLEDGE & PLAYBOOKS", fill=TEXT_DIM, font=FONT_MONO_SM)
        d.text((60, 245), "📁 Active Workflows", fill=COLOR_CYAN, font=FONT_BODY)
        d.text((70, 275), "├ ⚡ stripe-qbo-sync", fill=TEXT_MUTED, font=FONT_MONO_SM)
        d.text((70, 300), "└ ⚡ e2e-canary", fill=TEXT_MUTED, font=FONT_MONO_SM)
        d.text((60, 340), "🧠 Learned Skills", fill=COLOR_PURPLE, font=FONT_BODY)
        d.text((70, 370), "├ ✦ bank-reconcile", fill=TEXT_MUTED, font=FONT_MONO_SM)
        d.text((70, 395), "└ ✦ 100x-desktop-ide", fill=TEXT_MUTED, font=FONT_MONO_SM)
        
        # Center Pane: Dot Grid Canvas
        cx1, cy1, cx2, cy2 = 335, 195, WIDTH - 420, HEIGHT - 110
        d.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=BG_CANVAS, outline=BORDER_COLOR)
        draw_dot_grid(d, cx1, cy1, cx2, cy2)
        d.text((cx1 + 20, cy1 + 15), "LIVE EXECUTION CANVAS", fill=TEXT_DIM, font=FONT_MONO_SM)
        
        # Right Pane: Decision HUD
        rx1, ry1, rx2, ry2 = WIDTH - 405, 195, WIDTH - 40, HEIGHT - 110
        d.rounded_rectangle([rx1, ry1, rx2, ry2], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((rx1 + 20, ry1 + 15), "EXECUTIVE DECISION HUD", fill=TEXT_DIM, font=FONT_MONO_SM)
        
        # Phase 1: Typing in Command Bar (0 - 4s)
        typed_len = min(len(prompt_text), int(t * 22))
        curr_typed = prompt_text[:typed_len]
        
        cmd_y = HEIGHT - 85
        d.rounded_rectangle([WIDTH//2 - 380, cmd_y, WIDTH//2 + 380, cmd_y + 55], radius=28, fill=(20, 24, 34), outline=(70, 80, 110), width=1)
        d.text((WIDTH//2 - 355, cmd_y + 16), "⚡ " + curr_typed + ("|" if (f//10)%2==0 else ""), fill=TEXT_MAIN, font=FONT_BODY)
        d.rounded_rectangle([WIDTH//2 + 320, cmd_y + 12, WIDTH//2 + 360, cmd_y + 42], radius=6, fill=(35, 40, 55))
        d.text((WIDTH//2 + 328, cmd_y + 18), "⌘K", fill=TEXT_MUTED, font=FONT_MONO_SM)
        
        # Phase 2: Workflow Nodes Appear (4s - 8s)
        if t >= 3.5:
            # Nodes
            draw_card_node(d, cx1 + 40, cy1 + 180, 220, 110, "Trigger", "Daily 06:00 UTC", "cron: 0 6 * * *", COLOR_CYAN, active_glow=(t>=4.0))
            draw_bezier_wire(d, cx1 + 260, cy1 + 235, cx1 + 310, cy1 + 235, color=COLOR_CYAN if t>=5.0 else BORDER_COLOR, pulse=(t>=5.0))
            
            draw_card_node(d, cx1 + 310, cy1 + 180, 230, 110, "Ingest & OCR", "Stripe + QBO Feed", "Parse CSV & Invoices", COLOR_PURPLE, active_glow=(t>=5.5))
            draw_bezier_wire(d, cx1 + 540, cy1 + 235, cx1 + 590, cy1 + 235, color=COLOR_AMBER if t>=6.5 else BORDER_COLOR, pulse=(t>=6.5))
            
            # Math verify gate
            status = "FAIL (Δ=$14.50)" if t>=7.0 else "Calculating..."
            draw_card_node(d, cx1 + 590, cy1 + 180, 240, 110, "Verify Gate", "Deterministic Math", "verify_balance.py", COLOR_AMBER, active_glow=(t>=7.0), status_badge=status)
            draw_bezier_wire(d, cx1 + 830, cy1 + 235, cx1 + 880, cy1 + 235, color=COLOR_RED if t>=7.5 else BORDER_COLOR)
            
            draw_card_node(d, cx1 + 880, cy1 + 180, 220, 110, "Human Gate", "Hard Approval Lock", "exit 5: gate-blocked", COLOR_RED if t>=7.5 else TEXT_DIM, active_glow=(t>=7.5))
            
        # Phase 3: Decision Card Appears (8s - 12s)
        if t >= 7.5:
            # Render Executive Decision Card
            d.rounded_rectangle([rx1 + 15, ry1 + 50, rx2 - 15, ry1 + 240], radius=10, fill=(30, 25, 20), outline=COLOR_AMBER, width=2)
            d.text((rx1 + 30, ry1 + 65), "Approval Lock #108", fill=COLOR_AMBER, font=FONT_MONO_SM)
            d.text((rx1 + 30, ry1 + 90), "Reconcile Discrepancy", fill=TEXT_MAIN, font=FONT_TITLE)
            d.text((rx1 + 30, ry1 + 125), "Stripe $1,450.00 vs QBO $1,435.50\nΔ = $14.50 (Unmatched fee)", fill=TEXT_MUTED, font=FONT_MONO_SM)
            
            # Approve Button
            appr_fill = COLOR_EMERALD if t < 10.0 else (80, 220, 150)
            d.rounded_rectangle([rx1 + 30, ry1 + 180, rx1 + 180, ry1 + 220], radius=8, fill=appr_fill)
            d.text((rx1 + 45, ry1 + 192), "✓ Approve (↵)", fill=(0,0,0), font=FONT_BODY)
            
            # Deny Button
            d.rounded_rectangle([rx1 + 195, ry1 + 180, rx2 - 30, ry1 + 220], radius=8, fill=(40, 20, 20), outline=COLOR_RED)
            d.text((rx1 + 215, ry1 + 192), "✗ Deny (⎋)", fill=COLOR_RED, font=FONT_BODY)
            
        if t >= 10.0:
            # Action committed
            d.rounded_rectangle([rx1 + 15, ry1 + 260, rx2 - 15, ry1 + 330], radius=8, fill=(16, 40, 25), outline=COLOR_EMERALD)
            d.text((rx1 + 30, ry1 + 275), "✓ Nonce Consumed & Logged", fill=COLOR_EMERALD, font=FONT_BODY)
            d.text((rx1 + 30, ry1 + 300), "Ledger updated: exit 0 (0.004s)", fill=TEXT_MUTED, font=FONT_MONO_SM)
            
        # On-Screen Explanatory Banner
        banner_text = "DEMO 1: NATURAL LANGUAGE TO DETERMINISTIC HARD-GATED WORKFLOW" if t<4.0 else \
                      ("SIMULATING ZERO-LLM MATH VERIFICATION GATE (FAILS CLOSED ON Δ > $0.00)" if t<8.0 else \
                       "EXECUTIVE DECISION CARD: SINGLE-USE NONCE CONSUMED UPON APPROVAL")
        d.rounded_rectangle([WIDTH//2 - 450, 60, WIDTH//2 + 450, 100], radius=8, fill=(15, 20, 30), outline=COLOR_CYAN)
        d.text((WIDTH//2 - 430, 70), banner_text, fill=COLOR_CYAN, font=FONT_MONO_SM)
        
        img.save(proc.stdin, 'PNG')

    proc.stdin.close()
    proc.wait()
    print("Demo 1 rendered:", out_path)

def render_video_2():
    """Demo 2: Award Inbound -> 100x Upskilling in Sandbox -> GTM Campaign Synthesis"""
    out_path = '/Users/ai/rooms/devops/assets/demos/anton_demo_2_award_gtm_upskilling.mp4'
    proc = subprocess.Popen([
        '/opt/homebrew/bin/ffmpeg', '-y', '-f', 'image2pipe', '-vcodec', 'png',
        '-r', str(FPS), '-i', '-', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', out_path
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    total_frames = 14 * FPS
    
    for f in range(total_frames):
        t = f / FPS
        img = create_base_frame(son_of_anton=False)
        d = ImageDraw.Draw(img)
        
        # 3 Column Layout
        cx1, cy1, cx2, cy2 = 335, 195, WIDTH - 420, HEIGHT - 110
        d.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=BG_CANVAS, outline=BORDER_COLOR)
        draw_dot_grid(d, cx1, cy1, cx2, cy2)
        
        # Left Navigator
        d.rounded_rectangle([40, 195, 320, HEIGHT - 110], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((60, 215), "SECOND BRAIN MEMORY", fill=TEXT_DIM, font=FONT_MONO_SM)
        d.text((60, 245), "🧠 Learned Skills", fill=COLOR_PURPLE, font=FONT_BODY)
        
        if t >= 7.0:
            d.text((70, 275), "✦ 100x-gtm-strategist", fill=COLOR_EMERALD, font=FONT_MONO_SM)
            d.text((70, 300), "✦ 100x-pr-publicity", fill=COLOR_EMERALD, font=FONT_MONO_SM)
        else:
            d.text((70, 275), "(detecting missing skills...)", fill=TEXT_DIM, font=FONT_MONO_SM)
            
        d.text((60, 340), "📑 GTM Artifacts", fill=COLOR_CYAN, font=FONT_BODY)
        if t >= 9.5:
            d.text((70, 370), "├ 📄 award-marketing-plan.md", fill=TEXT_MAIN, font=FONT_MONO_SM)
            d.text((70, 395), "├ 📅 content-calendar.md", fill=TEXT_MAIN, font=FONT_MONO_SM)
            d.text((70, 420), "└ 📰 pr-outreach-list.md", fill=TEXT_MAIN, font=FONT_MONO_SM)
            
        # Right HUD
        rx1, ry1, rx2, ry2 = WIDTH - 405, 195, WIDTH - 40, HEIGHT - 110
        d.rounded_rectangle([rx1, ry1, rx2, ry2], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((rx1 + 20, ry1 + 15), "AMBITION GOVERNOR HUD", fill=TEXT_DIM, font=FONT_MONO_SM)
        
        # Stage 1: Inbound Email (0 - 3s)
        draw_card_node(d, cx1 + 40, cy1 + 180, 230, 110, "Inbound Event", "Award Notification", "2026 SaaS Innovation", COLOR_CYAN, active_glow=True)
        draw_bezier_wire(d, cx1 + 270, cy1 + 235, cx1 + 330, cy1 + 235, color=COLOR_PURPLE if t>=2.0 else BORDER_COLOR, pulse=(t>=2.0))
        
        # Stage 2: Governor Scoring (2s - 5s)
        draw_card_node(d, cx1 + 330, cy1 + 180, 230, 110, "Ambition Engine", "Score: EV=0.95", "Feasibility: High", COLOR_PURPLE, active_glow=(t>=2.5))
        draw_bezier_wire(d, cx1 + 560, cy1 + 235, cx1 + 620, cy1 + 235, color=COLOR_AMBER if t>=4.5 else BORDER_COLOR, pulse=(t>=4.5))
        
        # Stage 3: Sandbox Self-Upskilling (4.5s - 8s)
        sandbox_state = "PASS (100%)" if t>=7.0 else "Synthesizing Skills..."
        draw_card_node(d, cx1 + 620, cy1 + 180, 250, 110, "100x Sandbox", "Self-Upskilling Loop", "100x-gtm + 100x-pr", COLOR_AMBER, active_glow=(t>=5.0), status_badge=sandbox_state)
        draw_bezier_wire(d, cx1 + 870, cy1 + 235, cx1 + 930, cy1 + 235, color=COLOR_EMERALD if t>=7.5 else BORDER_COLOR, pulse=(t>=7.5))
        
        # Stage 4: Campaign Output (7.5s - 14s)
        draw_card_node(d, cx1 + 930, cy1 + 180, 240, 110, "GTM Engine", "Campaign Generated", "3 Artifacts in Vault", COLOR_EMERALD, active_glow=(t>=8.0))
        
        # Right Panel: Live GTM Deck & Decision
        if t >= 9.0:
            d.rounded_rectangle([rx1 + 15, ry1 + 50, rx2 - 15, ry1 + 280], radius=10, fill=(20, 30, 25), outline=COLOR_EMERALD, width=2)
            d.text((rx1 + 25, ry1 + 65), "Executive Launch Decision #104", fill=COLOR_EMERALD, font=FONT_MONO_SM)
            d.text((rx1 + 25, ry1 + 90), "2026 SaaS Award GTM", fill=TEXT_MAIN, font=FONT_TITLE)
            d.text((rx1 + 25, ry1 + 125), "• 2-Week Multi-Channel Content Calendar\n• 4 Pitches drafted (TechCrunch/VentureBeat)\n• 6 Social hooks ready for review", fill=TEXT_MUTED, font=FONT_MONO_SM)
            
            d.rounded_rectangle([rx1 + 25, ry1 + 220, rx2 - 25, ry1 + 265], radius=8, fill=COLOR_EMERALD)
            d.text((rx1 + 45, ry1 + 235), "⚡ Approve & Schedule Launch (↵)", fill=(0,0,0), font=FONT_BODY)
            
        banner_text = "DEMO 2: INBOUND AWARD EVENT TRIGGER" if t<3.5 else \
                      ("AUTONOMOUS 100x UPSKILLING IN ISOLATED SANDBOX CONTAINER" if t<7.5 else \
                       "STAFF-LEVEL GTM CAMPAIGN & CONTENT CALENDAR SYNTHESIZED IN SECOND BRAIN")
        d.rounded_rectangle([WIDTH//2 - 450, 60, WIDTH//2 + 450, 100], radius=8, fill=(15, 20, 30), outline=COLOR_PURPLE)
        d.text((WIDTH//2 - 430, 70), banner_text, fill=COLOR_PURPLE, font=FONT_MONO_SM)
        
        img.save(proc.stdin, 'PNG')
        
    proc.stdin.close()
    proc.wait()
    print("Demo 2 rendered:", out_path)

def render_video_3():
    """Demo 3: Son of Anton Mode Overdrive (Permissionless Auto-Bypass)"""
    out_path = '/Users/ai/rooms/devops/assets/demos/anton_demo_3_son_of_anton_overdrive.mp4'
    proc = subprocess.Popen([
        '/opt/homebrew/bin/ffmpeg', '-y', '-f', 'image2pipe', '-vcodec', 'png',
        '-r', str(FPS), '-i', '-', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', out_path
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    total_frames = 11 * FPS
    
    for f in range(total_frames):
        t = f / FPS
        son_active = (t >= 4.5)
        img = create_base_frame(son_of_anton=son_active)
        d = ImageDraw.Draw(img)
        
        cx1, cy1, cx2, cy2 = 335, 195, WIDTH - 420, HEIGHT - 110
        d.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=BG_CANVAS, outline=BORDER_COLOR)
        draw_dot_grid(d, cx1, cy1, cx2, cy2)
        
        rx1, ry1, rx2, ry2 = WIDTH - 405, 195, WIDTH - 40, HEIGHT - 110
        d.rounded_rectangle([rx1, ry1, rx2, ry2], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        
        # Center Canvas: Queue of 4 Gated Workflows
        tasks = [
            ("Payout: $450 Vendor", "gate: money"),
            ("Outbound Email: Acron Corp", "gate: outbound"),
            ("Payout: $1,200 Contractor", "gate: money"),
            ("Promote Skill: 100x-seo", "gate: skill")
        ]
        
        for i, (tname, tgate) in enumerate(tasks):
            ny = cy1 + 60 + i * 105
            node_color = COLOR_EMERALD if son_active else COLOR_AMBER
            tag_name = "Auto-Bypassed ⚡" if son_active else "Gated (Blocked)"
            draw_card_node(d, cx1 + 100, ny, 300, 85, tgate, tname, tag_name, node_color, active_glow=son_active)
            draw_bezier_wire(d, cx1 + 400, ny + 42, cx1 + 550, ny + 42, color=node_color, pulse=son_active)
            draw_card_node(d, cx1 + 550, ny, 260, 85, "Outcome", "Executed Instantly" if son_active else "Waiting for Human", "exit 0" if son_active else "exit 5", node_color)
            
        # Right Panel: Ledger Live Stream
        d.text((rx1 + 20, ry1 + 15), "RUNS.JSONL AUDIT STREAM", fill=TEXT_DIM, font=FONT_MONO_SM)
        
        if not son_active:
            d.text((rx1 + 20, ry1 + 60), "5 Approvals Queued.\nHalting at human boundary.", fill=TEXT_MUTED, font=FONT_MONO_SM)
        else:
            d.text((rx1 + 20, ry1 + 60), "⚡ PERMISSIONLESS MODE ENGAGED", fill=COLOR_AMBER, font=FONT_BODY)
            for j, (tname, _) in enumerate(tasks):
                d.text((rx1 + 20, ry1 + 100 + j * 45), f"✓ {tname[:20]}\n  [exit 0; son_of_anton_bypass]", fill=COLOR_EMERALD, font=FONT_MONO_SM)
                
            d.rounded_rectangle([rx1 + 20, ry1 + 300, rx2 - 20, ry1 + 360], radius=8, fill=(30, 25, 10), outline=COLOR_AMBER)
            d.text((rx1 + 30, ry1 + 315), "Daily Token Spend Budget:", fill=COLOR_AMBER, font=FONT_MONO_SM)
            d.text((rx1 + 30, ry1 + 335), "$0.042 / $5.00 Cap (Safe)", fill=TEXT_MAIN, font=FONT_BODY)
            
        banner_text = "STANDARD SAFE MODE: 5 WORKFLOWS HALTED AT HUMAN GATE BOUNDARY" if not son_active else \
                      "⚡ SON OF ANTON MODE ACTIVE: AUTONOMOUS BYPASS WITH FULL AUDIT LOGGING & BUDGET ENFORCEMENT"
        b_color = COLOR_AMBER if son_active else COLOR_CYAN
        d.rounded_rectangle([WIDTH//2 - 450, 60, WIDTH//2 + 450, 100], radius=8, fill=(15, 20, 30), outline=b_color)
        d.text((WIDTH//2 - 430, 70), banner_text, fill=b_color, font=FONT_MONO_SM)
        
        img.save(proc.stdin, 'PNG')
        
    proc.stdin.close()
    proc.wait()
    print("Demo 3 rendered:", out_path)

if __name__ == '__main__':
    render_video_1()
    render_video_2()
    render_video_3()
    print("All 3 demo videos created successfully!")

def render_video_4():
    """Demo 4: Conversational Chat in ⌘K + In-App Markdown Reader Drawer"""
    out_path = '/Users/ai/rooms/devops/assets/demos/anton_demo_4_markdown_reader_and_chat.mp4'
    proc = subprocess.Popen([
        '/opt/homebrew/bin/ffmpeg', '-y', '-f', 'image2pipe', '-vcodec', 'png',
        '-r', str(FPS), '-i', '-', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p',
        '-crf', '18', out_path
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    total_frames = 12 * FPS
    prompt_text = "Show me our newly learned 100x GTM strategy protocol"
    
    for f in range(total_frames):
        t = f / FPS
        img = create_base_frame(son_of_anton=False)
        d = ImageDraw.Draw(img)
        
        # 3 Column Base
        cx1, cy1, cx2, cy2 = 335, 195, WIDTH - 420, HEIGHT - 110
        d.rounded_rectangle([cx1, cy1, cx2, cy2], radius=12, fill=BG_CANVAS, outline=BORDER_COLOR)
        draw_dot_grid(d, cx1, cy1, cx2, cy2)
        
        # Left Navigator
        d.rounded_rectangle([40, 195, 320, HEIGHT - 110], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((60, 215), "INTERACTIVE MEMORY", fill=TEXT_DIM, font=FONT_MONO_SM)
        d.text((60, 245), "🧠 100x Learned Skills", fill=COLOR_PURPLE, font=FONT_BODY)
        d.text((70, 275), "✦ 100x-gtm-strategist.md ➜", fill=COLOR_EMERALD if t>=6.0 else TEXT_MUTED, font=FONT_MONO_SM)
        d.text((70, 300), "✦ 100x-pr-publicity.md ➜", fill=TEXT_MUTED, font=FONT_MONO_SM)
        d.text((70, 325), "✦ 100x-desktop-ide.md ➜", fill=TEXT_MUTED, font=FONT_MONO_SM)
        
        # Stage 1: Typing conversational prompt in ⌘K (0 - 4s)
        typed_len = min(len(prompt_text), int(t * 22))
        curr_typed = prompt_text[:typed_len]
        
        cmd_y = HEIGHT - 85
        d.rounded_rectangle([WIDTH//2 - 380, cmd_y, WIDTH//2 + 380, cmd_y + 55], radius=28, fill=(20, 24, 34), outline=(70, 80, 110), width=1)
        d.text((WIDTH//2 - 355, cmd_y + 16), "⚡ " + curr_typed + ("|" if (f//10)%2==0 else ""), fill=TEXT_MAIN, font=FONT_BODY)
        d.rounded_rectangle([WIDTH//2 + 320, cmd_y + 12, WIDTH//2 + 360, cmd_y + 42], radius=6, fill=(35, 40, 55))
        d.text((WIDTH//2 + 328, cmd_y + 18), "⌘K", fill=TEXT_MUTED, font=FONT_MONO_SM)
        
        # Stage 2: Cognitive Research HUD (4s - 6s)
        rx1, ry1, rx2, ry2 = WIDTH - 405, 195, WIDTH - 40, HEIGHT - 110
        d.rounded_rectangle([rx1, ry1, rx2, ry2], radius=12, fill=(18, 21, 28), outline=BORDER_COLOR)
        d.text((rx1 + 20, ry1 + 15), "COGNITIVE REASONING STREAM", fill=COLOR_PURPLE, font=FONT_MONO_SM)
        if t >= 4.0:
            d.text((rx1 + 20, ry1 + 50), "• Querying Second Brain graph (vault.db)\n• Parsing frontmatter & core axioms\n• Opening slide-out Markdown Reader...", fill=TEXT_MUTED, font=FONT_MONO_SM)
            
        # Stage 3: Slide-out Markdown Reader Drawer (6s - 12s)
        if t >= 5.5:
            drawer_w = 680
            dx1 = WIDTH - drawer_w
            d.rectangle([dx1, 50, WIDTH, HEIGHT], fill=(18, 21, 30), outline=BORDER_COLOR, width=2)
            
            # Header
            d.rectangle([dx1, 50, WIDTH, 110], fill=(24, 28, 40))
            d.text((dx1 + 30, 72), "100x-gtm-strategist.md", fill=TEXT_MAIN, font=FONT_TITLE)
            d.text((WIDTH - 50, 70), "✕", fill=TEXT_MUTED, font=FONT_TITLE)
            
            # Markdown Content Rendered
            md_y = 135
            d.rounded_rectangle([dx1 + 30, md_y, dx1 + 260, md_y + 30], radius=6, fill=(16, 45, 30))
            d.text((dx1 + 40, md_y + 7), "SANDBOX VERIFIED · CONFIDENCE 0.98", fill=COLOR_EMERALD, font=FONT_MONO_SM)
            
            md_y += 50
            d.text((dx1 + 30, md_y), "# 100x Go-To-Market Strategist", fill=TEXT_MAIN, font=FONT_TITLE)
            md_y += 40
            d.text((dx1 + 30, md_y), "Staff-level GTM & product launch protocol.", fill=TEXT_MUTED, font=FONT_BODY)
            
            md_y += 35
            d.text((dx1 + 30, md_y), "## Core Axioms & Playbook", fill=COLOR_CYAN, font=FONT_SUB)
            md_y += 35
            axioms = [
                "1. First-Principles Hook: Map market urgency to core axioms.",
                "2. Launch Sequencing: Embargo ➔ Social ➔ Customer ➔ Press.",
                "3. Conversion Flywheels: Convert proof into high-intent inbound."
            ]
            for ax in axioms:
                d.text((dx1 + 40, md_y), ax, fill=TEXT_MAIN, font=FONT_BODY)
                md_y += 30
                
            md_y += 15
            d.rounded_rectangle([dx1 + 30, md_y, WIDTH - 30, md_y + 110], radius=8, fill=(10, 12, 16), outline=(40, 45, 60))
            d.text((dx1 + 45, md_y + 15), "```yaml\nname: 100x-gtm-strategist\ntarget_capability: autonomous_launch_orchestration\n```", fill=COLOR_CYAN, font=FONT_MONO_SM)
            
        banner_text = "CONVERSATIONAL PROMPTS IN ⌘K: ASK QUESTIONS & SEARCH SECOND BRAIN" if t<5.5 else \
                      "IN-APP MARKDOWN READER: FULL RESEARCH & PROTOCOL TRANSPARENCY"
        d.rounded_rectangle([WIDTH//2 - 450, 60, WIDTH//2 + 450, 100], radius=8, fill=(15, 20, 30), outline=COLOR_EMERALD)
        d.text((WIDTH//2 - 430, 70), banner_text, fill=COLOR_EMERALD, font=FONT_MONO_SM)
        
        img.save(proc.stdin, 'PNG')

    proc.stdin.close()
    proc.wait()
    print("Demo 4 rendered:", out_path)

if __name__ == '__main__':
    render_video_4()
