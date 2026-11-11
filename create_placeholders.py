from pathlib import Path
from html import escape
OUT=Path(__file__).parent/'static/img'; OUT.mkdir(exist_ok=True)
START='''<svg xmlns="http://www.w3.org/2000/svg" width="700" height="620" viewBox="0 0 700 620"><defs><linearGradient id="bg" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#f0f1f2"/><stop offset="1" stop-color="#e3e6e7"/></linearGradient><linearGradient id="glass" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#b3c2c8"/><stop offset=".52" stop-color="#e2e9e9"/><stop offset="1" stop-color="#909fa4"/></linearGradient><linearGradient id="dark" x1="0" x2="1" y1="0" y2="0"><stop stop-color="#242a2d"/><stop offset=".45" stop-color="#52595b"/><stop offset="1" stop-color="#22272a"/></linearGradient><linearGradient id="wood" x1="0" x2="1" y1="0" y2="0"><stop stop-color="#a79278"/><stop offset=".52" stop-color="#c6b498"/><stop offset="1" stop-color="#92816b"/></linearGradient><filter id="shadow" x="-20%" y="-20%" width="150%" height="150%"><feGaussianBlur stdDeviation="17"/></filter></defs><rect width="700" height="620" fill="url(#bg)"/><path d="M0 485h700" stroke="#d7dbdc" stroke-width="2"/><path d="M0 486h700v134H0z" fill="#e5e7e8"/><path d="M55 70H645" stroke="#ffffff" opacity=".65"/><ellipse cx="353" cy="502" rx="215" ry="27" fill="#8f969a" opacity=".26" filter="url(#shadow)"/>'''
END='''<text x="36" y="580" font-family="Arial,sans-serif" font-size="11" font-weight="bold" letter-spacing="3" fill="#8c9398">ESQUADRA  /  CATÁLOGO</text></svg>'''

def rect(x,y,w,h,fill,stroke='#24292d',sw=12,rx=0):
 return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def line(x1,y1,x2,y2,width=7,stroke='#343a3e'):
 return f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{stroke}" stroke-width="{width}"/>'

def write(name,content):
 (OUT/name).write_text(START+content+END,encoding='utf8')

# Alumínio: painel frisado e maçaneta de aço
s=rect(247,97,212,389,'url(#dark)','#161b1e',13)
for y in [156,208,260,312,364,416]:
 s+=line(257,y,449,y,4,'#8a9293')+line(258,y+4,449,y+4,2,'#191e21')
s+=rect(418,300,7,44,'#dfe1df','#9b9f9d',2,3)+rect(260,110,184,19,'#454b4e','#343a3e',1)
write('porta-aluminio.svg',s)

# Janela alumínio: correr duas folhas
s=rect(170,160,365,277,'url(#glass)','#22282b',16)
s+=rect(190,178,164,239,'url(#glass)','#353d42',8)+rect(357,178,158,239,'url(#glass)','#353d42',8)
s+=line(350,174,350,419,10,'#21272b')+line(365,174,365,419,5,'#8f9899')
s+=rect(337,286,6,29,'#e2e4e3','#687176',2,3)+rect(371,286,6,29,'#e2e4e3','#687176',2,3)
s+='<path d="m196 405 145-204M377 408 509 220" stroke="#fff" opacity=".18" stroke-width="10"/>'
write('janela-aluminio.svg',s)

# Sacada 4 folhas
s=rect(150,82,399,412,'url(#glass)','#232729',15)
for x in [163,261,359,457]:
 s+=rect(x,94,94,387,'url(#glass)','#3a4043',6)
s+=line(357,95,357,479,9,'#262b2e')+line(249,95,249,479,4,'#6e797c')+line(455,95,455,479,4,'#6e797c')
s+=rect(343,277,7,31,'#f1f1ed','#737b7d',1,3)+rect(365,277,7,31,'#f1f1ed','#737b7d',1,3)
s+='<path d="M175 470l78-190 88-154M405 475l114-205" stroke="#fff" opacity=".15" stroke-width="10"/>'
write('porta-sacada.svg',s)

# Porta madeira com frisos
s=rect(251,96,209,390,'url(#wood)','#766754',13)
s+=rect(269,121,174,143,'none','#897a66',7)+rect(269,276,174,184,'none','#897a66',7)
s+=line(275,132,436,132,2,'#e6d9c4')+line(274,281,438,281,2,'#e6d9c4')
s+=rect(414,302,7,51,'#dfdedb','#76726a',2,3)
s+='<path d="M315 103v375M378 103v375" stroke="#f0e6d8" stroke-width="1" opacity=".20"/>'
write('porta-madeira.svg',s)

# Balcão: lower windows, horizontal 3 panes
s=rect(153,205,400,243,'url(#glass)','#272c30',15)
for x in [170,295,420]:
 s+=rect(x,222,118,208,'url(#glass)','#3b4448',7)
s+=line(294,219,294,428,7,'#282e31')+line(420,219,420,428,7,'#282e31')
s+=rect(282,309,5,27,'#dde0e0','#808688',1,3)
s+=rect(408,309,5,27,'#dde0e0','#808688',1,3)
s+='<path d="M176 415l110-178m38 164 90-140" stroke="#fff" opacity=".16" stroke-width="11"/>'
write('balcao.svg',s)

# Janela madeira veneziana
s=rect(179,170,351,260,'url(#wood)','#746653',14)
for x in [192,359]:
 s+=rect(x,184,158,230,'url(#wood)','#756852',7)
 for y in range(198,405,16):
  s+=f'<path d="M{x+10} {y}h138l-4 8H{x+6}z" fill="#887967" stroke="#c9b89e" stroke-width="1"/>'
s+=line(354,182,354,416,10,'#776c5d')
s+=rect(332,289,5,36,'#d3cec6','#857a68',1,3)+rect(371,289,5,36,'#d3cec6','#857a68',1,3)
write('janela-madeira.svg',s)
print('SVGs generated:', len(list(OUT.glob('*.svg'))))
