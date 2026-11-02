"""Prepare grounded story copy and source matches for the full usable catalog."""
import hashlib
import json
import re
import sys
from pathlib import Path
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.single_pass import catalog,load_catalog_processor

# Copy describes color/tone, never spatial effects such as grain, glow or sharpness.
FAMILIES={
'mono':('让光影，成为照片的主角。','褪去颜色后，人物的神情、建筑的线条与物体的纹理接过视线。适合人像、街头与纪实片刻，让画面回到明暗之间。',['portrait-1','hk-2','coast','window','forest-1','portrait-7'],'黑白光影'),
'infra':('换一种灰阶，重新看见自然。','以黑白红外风格为灵感，让熟悉的植被与天空呈现另一种明暗关系。适合树林、海岸和有明显光影的场景，寻找更特别的自然表情。',['forest-1','autumn-2','coast','mountain','lotus'],'红外风格'),
'invert':('把熟悉的风景，翻转成另一种想象。','这是一种带有反相意味的创意效果，明暗与颜色会脱离日常观感。适合建筑、植物和抽象构图，用强烈变化为照片制造陌生感。',['hk-2','lotus','autumn-3','hk-1'],'创意反相'),
'portrait':('把一段温柔的情绪，留在照片里。','以人物为画面的落点，观察肤色、衣物与背景如何相互衬托。适合自然光人像、生活记录和有环境陪衬的半身构图，让照片多一点可回味的情绪。',['portrait-7','window','portrait-2','portrait-1','hk-1','portrait-3'],'人像情绪'),
'instant':('把今天，留成一张值得收藏的旧照片。','借用即时成像风格的色彩语言，让普通的物件和街角有了另一种年代感。适合咖啡、城市漫步与旅行小景，收藏不必隆重的日常。',['coffee','hk-1','beach-3','autumn-3','hk-2'],'即时成像风格'),
'expired':('让颜色，带一点岁月的偏心。','复古实验风格把色彩的变化当作表达的一部分。适合旧街、日常静物和季节片段，为清晰的现实留下一点不那么规整的记忆。',['coffee','hk-1','autumn-3','beach-3','hk-2'],'复古实验'),
'cross':('用一次大胆的色彩转向，打破日常。','交叉冲洗风格适合跳出熟悉的颜色关系。把它用在街景、植物或有多种色块的画面里，让同一个场景呈现更鲜明的个性。',['hk-2','lotus','autumn-3','hk-1','beach-3'],'交叉冲洗风格'),
'slide':('让旅途的颜色，值得再看一眼。','以胶片色彩为灵感，把注意力交给风景中的色彩关系。山谷、树叶与街头色块都是好的起点，让一段旅途有更清晰的视觉记忆。',['mountain','autumn-2','hk-2','lotus','beach-1'],'反转片风格'),
'chrome':('把城市与远方，收进一页旅行日记。','借用经典胶片的色彩语气，记录楼宇、山色与街边细节。适合旅行和日常扫街，让不同的地点拥有连贯的观看节奏。',['hk-2','mountain','autumn-3','coffee','beach-1'],'经典胶片风格'),
'negative':('让平常的一天，也有自己的色彩。','彩色负片风格适合把街景、人像与旅行片段串在一起。它关注日常场景里的色彩关系，适合寻找统一的相册气质。',['hk-1','portrait-2','beach-1','autumn-2','coffee'],'彩色负片风格'),
'cinema':('让一张照片，像故事中的一幕。','用明暗与色彩组织视线，让人物和环境产生联系。适合街头、旅行与环境人像，在静止的画面里留下一点叙事空间。',['hk-2','window','hk-16','portrait-3','coast'],'电影氛围'),
'night':('让夜晚的故事，从灯光里开始。','把街灯、招牌与周围环境放进同一幅构图，让不同的光源成为画面的节奏。适合夜街和有亮部点缀的环境，留住城市入夜后的气息。',['hk-16','window','hk-2','hk-1','coffee'],'夜色氛围'),
'daynight':('让白昼，走进蓝色的夜幕。','日转夜风格会重新组织白天照片的明暗与色彩。适合建筑、空旷街道和树影等题材，用一张日间原片尝试另一种时间感。',['hk-1','forest-1','beach-3','hk-2'],'日转夜'),
'teal':('让冷暖之间，发生一点故事。','以青橙色彩关系为表达方向，寻找环境冷色与画面暖色的呼应。适合城市、灯光与环境人像，让照片中的色块相互衬托。',['hk-2','hk-16','portrait-3','beach-1','coffee'],'青橙氛围'),
'forest':('让树林里的情绪，慢慢浮现。','把目光交给植物、树影与林间小路。适合有绿叶和自然纹理的场景，让同一片绿色也能有不同的情绪与季节感。',['forest-1','lotus','autumn-3','portrait-2','mountain'],'自然氛围'),
'landscape':('给山海与远方，一种新的表情。','在天空、植被和大地之间寻找色彩的呼应。适合山谷、海岸与旅行风景，让辽阔的场景也拥有属于自己的情绪。',['mountain','beach-1','autumn-3','forest-1','coast'],'风景表达'),
'warm':('给日常，多留一点温度。','以暖色氛围为灵感，适合咖啡、秋日树影与旅途小景。把熟悉的画面放慢一点，让颜色成为记忆的一部分。',['coffee','autumn-3','hk-1','beach-1','lotus'],'暖调氛围'),
'cool':('在冷色里，留住片刻安静。','以冷色氛围为表达方向，适合海岸、建筑与树影。选择层次清楚的场景，让颜色与空间共同带出安静、疏离或清新的感觉。',['coast','hk-2','forest-1','beach-3','mountain'],'冷调氛围'),
'moody':('让画面，留一点没有说完的情绪。','适合有阴影、纵深或局部光线的照片。用环境包围主体，让街角、树影和窗边片刻都有一份值得停留的氛围。',['forest-1','window','hk-16','hk-2','coast'],'情绪氛围'),
'soft':('让日常，带一点轻柔的语气。','适合窗边、海岸和简单的生活片段。留出呼吸感，让衣物、天空与背景之间的色彩关系成为照片温柔的一面。',['window','beach-1','portrait-7','lotus','coffee'],'柔和情绪'),
'vivid':('把喜欢的颜色，放在画面中央。','适合树叶、花卉、城市招牌等有明显色块的题材。让颜色参与构图，把平常的场景变成一次更鲜明的视觉表达。',['lotus','autumn-2','hk-2','mountain','hk-1'],'色彩表达'),
'neutral':('从熟悉的日常，发现新的感觉。','适合街头、旅行与生活静物。把同一个场景放进另一种色彩关系里，找到适合这一刻的观看方式。',['hk-1','beach-1','coffee','autumn-3','portrait-2'],'日常记录'),
}
CAPTIONS={
'coast':('海岸与礁石','浪花、海水与岩面同时入镜，适合观察深浅层次和自然纹理。'),
'hk-1':('城市的纵深','车流穿过高楼之间，立面与车身的色块让街头有了观看节奏。'),
'hk-2':('街头的色彩关系','电车、招牌与建筑交织在一起，适合感受这个风格如何组织复杂场景。'),
'hk-16':('灯光下的夜色','招牌、车灯与街边暗部相互陪衬，城市夜晚的气息藏在这些细节里。'),
'forest-1':('林间的一段安静','石径伸入树影，绿叶与地面的层次成为画面的主要语言。'),
'autumn-2':('抬头看见秋色','枝干划开天空，深浅叶片与树影一起记录季节的变化。'),
'autumn-3':('季节留在树梢','让叶片、天空与树干相互衬托，看看这个风格如何描绘秋天。'),
'portrait-1':('自然光里的表情','肤色、白衣和绿叶背景放在一起，让人物成为色彩关系的中心。'),
'portrait-2':('人物与环境','树下的人物与周围植被共同构图，把情绪留在一次自然的停顿里。'),
'portrait-3':('抬头的一瞬','面部受光与背景树影形成呼应，环境让人物的情绪有了落点。'),
'portrait-7':('侧脸的一刻','侧面的光线勾勒面部轮廓，白衣与背景衬托出安静的神情。'),
'beach-1':('海边的呼吸','天空、海浪与沙滩组成简单的层次，色彩的变化也变得容易感受。'),
'beach-3':('远方的一条线','桥梁横过平静海面，简洁构图把注意力留给天空与水面的关系。'),
'beach-6':('海浪停留的片刻','海面与沙滩之间保留清楚的层次，让风景用更简单的方式表达。'),
'coffee':('街角的生活片段','咖啡杯、木桌和街头背景共同入镜，把日常物件拍成一段有环境的记忆。'),
'window':('窗边的阅读时光','窗光落在人物与书页上，明亮窗外和室内阴影衬托出安静的片刻。'),
'white':('室内的柔软片刻','白色衣物与室内背景让肤色和明暗关系成为画面的重点。'),
'mountain':('山谷里的远方','积雪、山体与天空拉开空间，把旅途的辽阔留在一张照片里。'),
'lotus':('花与叶的对话','浅色花瓣被深浅绿叶包围，用自然色块呈现植物的层次。')}

def family(item, inversion=False):
 n=item['label'].lower().replace('_',' ').replace('-',' ')
 has=lambda *xs:any(x in n for x in xs)
 if inversion:return 'invert'
 if item['category']=='mono':return 'infra' if has('infra','hie','ir 400') else 'mono'
 if has('nightfromday','day for night'):return 'daynight'
 if has('expired','time zero','sepia','lofi','redscale'):return 'expired'
 if has('cross','xpro','x pro'):return 'cross'
 if has('polaroid','instant','fp 100'):return 'instant'
 if has('portra','portrait','pro neg','astia','160c','400h','800z'):return 'portrait'
 if has('teal','aqua and orange','amber & aqua','sedona'):return 'teal'
 if has('night','tungsten','blade runner','coronado','tensiongreen'):return 'night'
 if has('moody','horror','bleach','dense'):return 'moody'
 if has('forest','nature','humble'):return 'forest'
 if has('landscape'):return 'landscape'
 if has('velvia','provia','fortia','sensia','slide','ektar','elite'):return 'slide'
 if has('kodachrome','chrome','k64','k25','k99'):return 'chrome'
 if has('superia','negative','gold','vista','ultra','agfa'):return 'negative'
 if has('cinema','print','2383','2393','3510','3513','f 6800','f 8700'):return 'cinema'
 if has('warm','golden','honey','heatwave','oranges','reds','candle','w 8370','h 9110'):return 'warm'
 if has('cool','cold','blue','aqua','aspen','c 8120','c 9730'):return 'cool'
 if has('soft','faded','dusty','renata','bloom'):return 'soft'
 if has('vivid','pop','boost'):return 'vivid'
 return 'neutral'

def probe(processor):
 ramp=np.repeat(np.linspace(0,1,101,dtype=np.float32)[:,None],3,axis=1);processor.applyRGB(ramp);ramp=np.clip(ramp,0,1)
 lum=ramp@np.array([.2126,.7152,.0722]);mid=ramp[50];temp=float(mid[0]-mid[2]);tint=float(mid[1]-(mid[0]+mid[2])/2)
 return {'black':round(float(lum[0]),4),'mid':round(float(lum[50]),4),'span':round(float(lum[80]-lum[20]),4),'temp':round(temp,4),'tint':round(tint,4),'inversion':bool(lum[10]>lum[90])}

def copy(item,group,p):
 headline,body,_,tag=FAMILIES[group]; traits=[tag]
 if p['inversion']:tone='它会翻转常见的明暗关系，让熟悉的色块呈现反相般的变化。';traits+=['明暗反转','强烈个性']
 else:
  if p['span']>.72:tone='明暗反差更鲜明，亮部与阴影拉开距离';traits+=['鲜明反差']
  elif p['span']<.42:tone='明暗距离被收拢，画面呈现更平缓的层次';traits+=['柔化反差']
  else:tone='明暗之间保留了清晰的过渡';traits+=['层次过渡']
  if p['black']>.07:tone+='，暗部带着抬黑后的褪色感';traits+=['褪色暗部']
  elif p['mid']<.4:tone+='，中间调更深沉';traits+=['深沉中间调']
  elif p['mid']>.6:tone+='，中间调更明亮';traits+=['明亮中间调']
  elif group not in ['mono','infra'] and p['temp']>.055:tone+='，中性色偏向暖黄';traits+=['暖黄倾向']
  elif group not in ['mono','infra'] and p['temp']<-.055:tone+='，中性色偏向冷蓝';traits+=['冷蓝倾向']
  elif group not in ['mono','infra'] and p['tint']>.035:tone+='，中性色带一点绿调';traits+=['绿调倾向']
  elif group not in ['mono','infra'] and p['tint']<-.035:tone+='，中性色带一点洋红';traits+=['洋红倾向']
  else:traits+=['保留场景细节']
  tone+='。'
 name=item['label'].replace(' · 照片版','')
 return {'headline':headline,'description':f'在「{name}」中，{tone}{body}','traits':traits[:3]}

def main():
 folder=ROOT/'data/gallery-research/2026-10-31-full-stories';folder.mkdir(parents=True,exist_ok=True)
 store=ROOT/'data/style-gallery';current=json.loads((store/'current.json').read_text())['id'];manifest=json.loads((store/'builds'/current/'manifest.json').read_text())
 pool=json.loads((ROOT/'data/gallery-research/2026-10-31-batch02/source-pool.json').read_text());old=json.loads((ROOT/'prototypes/lut-studio/style-stories.json').read_text());pilots={i['lut_id']:i for i in old['items'] if i['lut_id'] in {'xmosaique-warm-instant','xmosaique-silver-mono','on1-amber-aqua'}}
 rows={r['id']:r for r in catalog()};scenes={s['id']:s for s in manifest['scenes']};stories=[];audit=[]
 for index,item in enumerate(manifest['items'],1):
  lut=item['id'];group=family(item)
  if item.get('availability','ready')!='ready':
   name=item['label'];meaning=FAMILIES[group][3] if group!='neutral' else '色彩风格'
   story={'lut_id':lut,'headline':f'探索「{name}」的色彩表达。','description':f'收录于 {item["collection"]} 的「{name}」。'+(f'从名称看，它指向{meaning}的表达方向。' if group!='neutral' else '具体的色彩与明暗特点，将在照片适配完成后结合真实样片介绍。')+'目前照片输入条件仍待确认，效果图将在适配后补齐。','traits':['已收录','待照片适配'],'examples':[]}
  elif lut in pilots:story=pilots[lut]
  else:
   cpu=load_catalog_processor(rows[lut]);p=probe(cpu);group=family(item,p['inversion']);story={'lut_id':lut,**copy(item,group,p),'examples':[]}
   primary=scenes[item['sample_id']]['source_sha256'];keys=list(FAMILIES[group][2]);seed=int(hashlib.sha256(lut.encode()).hexdigest()[:8],16);offset=seed%len(keys);keys=keys[offset:]+keys[:offset]
   # Avoid severe color casts on faces, while keeping one person for portrait-focused looks.
   if group not in ['mono','infra'] and (abs(p['temp'])>.16 or abs(p['tint'])>.12):keys=[k for k in keys if not k.startswith('portrait') and k not in ['window','white']]+['hk-1','autumn-3','coffee','lotus']
   keys += ['hk-2','beach-1','autumn-3','lotus']
   seen={primary}
   for key in keys:
    source=pool[key]
    if source['source_sha256'] in seen:continue
    seen.add(source['source_sha256']);title,caption=CAPTIONS[key]
    story['examples'].append({'title':title,'caption':caption,**source})
    if len(story['examples'])==3:break
   audit.append({'lut_id':lut,'label':item['label'],'family':group,'probe':p,'sources':[e['subject'] for e in story['examples']]})
  stories.append(story)
  if index%100==0:print('Configured',index,flush=True)
 config={'schema_version':1,'items':stories};(ROOT/'prototypes/lut-studio/style-stories.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n');(folder/'copy-evidence.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2));(folder/'baseline.json').write_text(json.dumps({'build_id':current,'configured':len(stories)}));print('Configured',len(stories),'stories')

if __name__=='__main__':main()
