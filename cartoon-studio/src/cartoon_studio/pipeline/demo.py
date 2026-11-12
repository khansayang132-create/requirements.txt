import json, hashlib
from pathlib import Path
from cartoon_studio.state import CharacterSpec, SceneSpec

def create_demo(root: Path):
    """Create an original, text-only sample universe; no external API or paid generation."""
    uid="mosslight-valley"
    universe={"id":uid,"title":"Mosslight Valley","premise":"Five tiny keepers protect the glowing seeds that help their forest recover after storms.","tone":"gentle adventure, humor, curiosity","world_rules":["glow-seeds respond to teamwork","each habitat has its own weather rhythm","problems are solved without cruelty"],"originality_note":"Created for this demo; no intentional use of existing franchise characters."}
    (root/"universes"/uid).mkdir(parents=True,exist_ok=True)
    (root/"universes"/uid/"universe.json").write_text(json.dumps(universe,indent=2))
    specs=[
    ("pipkin","Pipkin","moss rabbit",["curious","brave","impatient"],"A young burrow scout who maps safe paths.","#A98AD8"),
    ("brindle","Brindle","mushroom fox",["inventive","witty","restless"],"A tinkerer who builds tools from fallen twigs.","#D98255"),
    ("morrow","Morrow","pond turtle",["patient","thoughtful","gentle"],"A keeper of old forest stories.","#4C9DB0"),
    ("tilli","Tilli","sun-moth",["optimistic","bold","forgetful"],"A night flier who reads patterns in the stars.","#E7C84F"),
    ("oakley","Oakley","acorn badger",["loyal","careful","shy"],"A gardener who knows every root in the valley.","#8A654B")]
    chars=[]
    for cid,name,species,traits,back,palette in specs:
      data={"id":cid,"name":name,"species":species,"age_category":"young adventurer","personality":traits,"backstory":back,"strengths":[traits[0],"teamwork"],"weaknesses":[traits[2]],"visual_design":{"face":"soft rounded muzzle, large readable eyes","body":"compact stylized proportions","surface":"velvety matte fur or shell","clothing":"one practical signature accessory","distinctive_feature":f"silhouette and markings unique to {name}"},"animation_design":{"walk":"species-specific bouncy gait","run":"short energetic stride","idle":"subtle breathing and blink","talk":"clear mouth shapes and head beats","signature":"one recognizable gesture"},"palette":{"primary":palette,"secondary":"#F2E6C8","accent":"#6B8F58"}}
      h=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(); data["reference_hash"]=h
      d=root/"character-bibles"/cid; d.mkdir(parents=True,exist_ok=True); (d/"character.json").write_text(json.dumps(data,indent=2)); chars.append(data)
    (root/"universes"/uid/"characters.json").write_text(json.dumps(chars,indent=2))
    story={"title":"The Seed That Wouldn't Shine","duration_seconds":60,"age_range":"5–9","moral":"A small contribution can matter when everyone works together.","scenes":[
      {"number":1,"duration":8,"location":"Fernbridge clearing","action":"A storm cloud passes; one glow-seed remains dark.","dialogue":[["Pipkin","The last seed isn't glowing!"],["Tilli","Maybe it needs a little sunshine." ]]},
      {"number":2,"duration":12,"location":"Mossy creek","action":"Brindle builds a leaf reflector, but it slips into the water.","dialogue":[["Brindle","My brilliant invention has become a boat." ]]},
      {"number":3,"duration":14,"location":"Root garden","action":"Oakley finds the seed is buried under a tangled root; Morrow suggests asking the roots gently.","dialogue":[["Morrow","Let's listen before we pull."],["Oakley","I can loosen the soil." ]]},
      {"number":4,"duration":16,"location":"Fernbridge clearing","action":"The friends combine reflected light, careful digging, and Tilli's wingbeat; the seed glows.","dialogue":[["Pipkin","Together did it!"],["Tilli","And nobody had to be a superhero." ]]},
      {"number":5,"duration":10,"location":"Valley panorama","action":"A new sprout unfurls; the friends celebrate as fireflies form a tiny crown.","dialogue":[["Morrow","Every little light belongs." ]]}
    ]}
    (root/"stories"/uid).mkdir(parents=True,exist_ok=True); (root/"stories"/uid/"episode-001.json").write_text(json.dumps(story,indent=2))
    board={"episode":story["title"],"shots":[{"scene":s["number"],"duration":s["duration"],"camera":"wide establishing → medium action → emotional close-up","lighting":"soft volumetric forest light","transition":"match cut or gentle dissolve","sound":"forest ambience + action-specific foley"} for s in story["scenes"]]}
    (root/"storyboards"/uid).mkdir(parents=True,exist_ok=True); (root/"storyboards"/uid/"episode-001.json").write_text(json.dumps(board,indent=2))
    return {"universe":str(root/"universes"/uid/"universe.json"),"characters":5,"story":str(root/"stories"/uid/"episode-001.json"),"storyboard":str(root/"storyboards"/uid/"episode-001.json"),"reference_images":"BLOCKED: no image provider credentials or generation approved; character bibles are text specs only"}
