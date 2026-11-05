"""Build sample_input/synthetic_show.zip, a tiny invented show in the Kuku screenplay format.

Everything here is made up for testing. It contains no real screenplay content.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def stamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:05.2f}"


def cue_block(label: str, start: float, end: float, text: str) -> str:
    shown = f'"{text}"' if label not in ("CAMERA", "ACTION", "SOUND FX") else text
    return f"**{label}:**\nStart: ({stamp(start)}) | End: ({stamp(end)})\n{shown}\n"


def episode_text(number: int, logline: str, notes: str, scenes: list[tuple[str, float, float, list[tuple[str, float, float, str]]]], uppercase: bool = False) -> str:
    parts = [f"EPISODE NUMBER: Episode {number}", f"EPISODE LOGLINE: {logline}", f"CONTINUITY NOTES: {notes}", "", "--- SCRIPT START ---", ""]
    for index, (heading, start, end, cues) in enumerate(scenes, start=1):
        names = ("SCENE HEADING", "SCENE START", "SCENE END", "ACTIONS AND DIALOGUE") if uppercase else ("Scene heading", "Scene start", "Scene end", "Actions and dialogue")
        parts += [f"SCENE {index:02d}", f"{names[0]}: {heading}", f"{names[1]}: {stamp(start)}", f"{names[2]}: {stamp(end)}", "", f"{names[3]}:", ""]
        for label, cue_start, cue_end, text in cues:
            parts.append(cue_block(label, cue_start, cue_end, text))
    parts += ["--- SCRIPT END ---", ""]
    return "\n".join(parts)


EPISODE_1 = [
    ("INT. HARBOUR COURTHOUSE - DAY", 0.0, 62.0, [
        ("CAMERA", 0.0, 2.0, "Wide shot of a crowded harbour courthouse."),
        ("ACTION", 0.5, 2.0, "Mara stands alone in the witness box, gripping the rail."),
        ("PROSECUTOR (Cold, Accusing)", 2.0, 4.5, "You sank that ship and let your own brother drown!"),
        ("CAMERA", 4.5, 7.0, "Close-up on Mara's shocked face."),
        ("MARA (Stunned)", 5.0, 6.5, "That is a lie."),
        ("PROSECUTOR (Scornful)", 7.0, 10.0, "Your brother trusted you with the harbour lights."),
        ("MARA (Desperate)", 10.5, 13.0, "I lit every lamp that night. I swear it."),
        ("CAMERA", 13.0, 16.0, "Medium shot of the judge leaning forward."),
        ("JUDGE (Stern)", 13.5, 16.0, "Then who put out the lamps, Miss Vale?"),
        ("MARA (Trembling)", 16.5, 18.5, "I do not know."),
        ("CAMERA", 18.5, 21.0, "Close-up on an old sailor in the crowd."),
        ("OLD SAILOR (O.S.) (Shouting)", 19.0, 21.0, "She is lying to save her own neck!"),
        ("MARA (Furious)", 21.5, 24.0, "My brother is dead, and you want me to hang for it?"),
        ("PROSECUTOR (Menacing)", 24.5, 27.5, "I want the truth, and I have a witness who saw you."),
        ("ACTION", 27.5, 30.0, "The courtroom doors slam open and a soaked woman staggers inside."),
        ("CAMERA", 27.5, 30.0, "Low angle on the doors crashing open."),
        ("WITNESS (Gasping)", 30.5, 33.0, "Stop this trial. Her brother is not dead."),
        ("CAMERA", 33.0, 36.0, "Close-up on Mara, frozen."),
        ("MARA (Whispering)", 33.5, 35.5, "What did you say?"),
        ("WITNESS (Urgent)", 36.0, 39.0, "He paid me to put out the lamps."),
        ("JUDGE (Booming)", 39.5, 42.0, "Who paid you? Say his name!"),
        ("WITNESS (Terrified)", 42.5, 45.0, "If I say it, he will kill us both."),
        ("CAMERA", 45.0, 48.0, "Slow push in on the witness as she lifts a shaking hand."),
        ("ACTION", 45.5, 48.0, "The witness lifts a shaking hand and points toward the front row."),
        ("WITNESS (Breathless)", 48.5, 51.0, "He is sitting right there."),
        ("CAMERA", 51.0, 56.0, "The crowd turns. Hold on Mara as she slowly follows the finger."),
        ("SOUND FX", 54.0, 60.0, "Low strings swell to a cliffhanger sting."),
        ("CAMERA", 56.0, 62.0, "Cut to black."),
    ]),
]

EPISODE_2 = [
    ("EXT. CLIFF PATH - NIGHT", 0.0, 30.0, [
        ("CAMERA", 0.0, 3.0, "Wide shot of waves far below a narrow cliff path."),
        ("TOMAS (Gentle)", 3.0, 5.0, "Did you eat today?"),
        ("MARA (Soft, Tired)", 5.5, 7.0, "A little."),
        ("TOMAS (Warm)", 7.5, 10.0, "The bakery sent bread for you again."),
        ("MARA (Quiet)", 10.5, 12.5, "That was kind of them."),
        ("CAMERA", 12.5, 16.0, "Medium two shot of them walking slowly."),
        ("TOMAS (Gentle)", 16.5, 19.0, "What time should we open the shop tomorrow?"),
        ("MARA (Calm)", 19.5, 22.0, "Nine, I suppose. Same as always."),
        ("TOMAS (Reassuring)", 22.5, 25.0, "It is over now. You are safe. Thank you for trusting me."),
        ("MARA (Relieved)", 25.5, 28.0, "Thank you. I found it easier to sleep last night."),
        ("CAMERA", 28.0, 30.0, "Fade out on the two of them walking home."),
    ]),
    ("INT. LIGHTHOUSE - NIGHT", 30.0, 80.0, [
        ("ACTION", 30.0, 32.5, "Mara pushes open the lighthouse door and freezes."),
        ("CAMERA", 30.0, 33.0, "Close-up on a fresh bloody handprint on the wall."),
        ("MARA (Horrified)", 33.0, 35.5, "Someone has been living in here!"),
        ("TOMAS (Alarmed)", 36.0, 38.0, "Get behind me. Now."),
        ("ACTION", 38.5, 41.0, "A figure lunges from the stairwell and slams Tomas against the wall."),
        ("MARA (Screaming)", 41.5, 43.0, "Let him go!"),
        ("HOODED MAN (Cold, Ominous)", 43.5, 46.5, "You should have stayed away from this light, sister."),
        ("MARA (Stunned)", 47.0, 49.0, "Only one person ever called me that."),
        ("CAMERA", 49.0, 52.0, "Close-up on the hood as a scarred hand starts to lift it."),
        ("HOODED MAN (Sinister)", 52.0, 55.0, "Did you really think the sea could kill me?"),
        ("MARA (Whispering, Terrified)", 55.5, 58.0, "You drowned. I buried an empty coffin for you."),
        ("HOODED MAN (Menacing)", 58.5, 61.0, "And tomorrow they will bury you in a full one."),
        ("ACTION", 61.5, 64.0, "He draws a harbour knife and steps toward her."),
        ("MARA (Desperate)", 64.5, 67.0, "What do you want from me?"),
        ("HOODED MAN (Chilling)", 67.5, 70.5, "Because you know what is under the lighthouse."),
        ("CAMERA", 70.5, 76.0, "Slow push in on Mara as the lamp above them goes dark."),
        ("SOUND FX", 72.0, 80.0, "A single thud, then silence."),
        ("CAMERA", 76.0, 80.0, "Black screen."),
    ]),
]

EPISODE_3 = [
    ("INT. VALE HOUSE - KITCHEN - DAY", 0.0, 44.0, [
        ("ACTION", 0.0, 3.0, "Mara sets a heavy iron key down on the kitchen table."),
        ("CAMERA", 0.0, 3.0, "Insert on the key landing on the wood."),
        ("MARA (Firm)", 3.5, 6.0, "This opens the room under the lighthouse."),
        ("AUNT ISOLDE (Sharp)", 6.5, 9.0, "Where did you get that?"),
        ("MARA (Accusing)", 9.5, 12.5, "You knew he was alive, and you let me bury him!"),
        ("AUNT ISOLDE (Cold)", 13.0, 16.0, "I knew what he stole. Everyone in this family did."),
        ("MARA (Outraged)", 16.5, 19.0, "You all lied to me for three years?"),
        ("AUNT ISOLDE (Calm, Cutting)", 19.5, 22.5, "We lied so you could keep your name clean..."),
        ("AUNT ISOLDE (Cold)", 22.5, 25.0, "...and so he could keep breathing."),
        ("MARA (Defiant)", 25.5, 28.0, "Then tell me what is in that room."),
        ("AUNT ISOLDE (Venomous)", 28.5, 31.5, "Open it, and you will hang beside your brother."),
        ("CAMERA", 31.5, 36.0, "Close-up on Mara's hand closing around the key."),
        ("MARA (Resolute)", 36.5, 39.0, "Then I will see you at the gallows, Aunt."),
        ("CAMERA", 39.0, 44.0, "Mara walks out and the door swings behind her."),
    ]),
]


def build(path: str | Path) -> Path:
    target = Path(path)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        folder = "The Lighthouse Debt"
        archive.writestr(f"{folder}/episode-001-Episode 900001.txt", episode_text(
            1, "Mara Vale is accused in court of drowning her brother, until a witness bursts in with a claim that changes everything.",
            "First episode.", EPISODE_1))
        archive.writestr(f"{folder}/episode-002-Episode 900002.txt", episode_text(
            2, "A quiet walk home turns violent when Mara discovers someone has been hiding in the lighthouse.",
            "Follows the courtroom scene.", EPISODE_2, uppercase=True))
        archive.writestr(f"{folder}/episode-003-Episode 900003.txt", episode_text(
            3, "Mara confronts her aunt with a key to a hidden room and learns the family has been lying.",
            "Follows the attack at the lighthouse.", EPISODE_3))
    return target


if __name__ == "__main__":
    print(build(Path(__file__).with_name("synthetic_show.zip")))
