from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeonCharacter:
    name: str
    color: str


@dataclass(frozen=True, slots=True)
class DialogueLine:
    speaker: str
    text: str


class DemoKeonWorld:
    _colors = ("#38bdf8", "#fb923c", "#a78bfa", "#34d399", "#f472b6", "#facc15")
    _conversations = (
        ("Selam! Demo Keon'u keşfediyorum.", "Hoş geldin, birlikte bakalım."),
        ("DemoPHO bugün nasıl yardımcı olabilir?", "Mesajını yaz, yerel demoda yanıtlayayım."),
        ("Daha fazla arkadaş ekleyebiliriz.", "Üstteki düğmeyle yeni bir çöp adam çağır!"),
    )

    def __init__(self) -> None:
        self.characters = [
            KeonCharacter("Keon", self._colors[0]),
            KeonCharacter("Mavi", self._colors[1]),
            KeonCharacter("DemoPHO", self._colors[2]),
        ]
        self._conversation_index = 0

    def add_character(self) -> KeonCharacter:
        number = len(self.characters) + 1
        character = KeonCharacter(
            name=f"Çöp Adam {number}",
            color=self._colors[(number - 1) % len(self._colors)],
        )
        self.characters.append(character)
        return character

    def next_conversation(self) -> tuple[DialogueLine, DialogueLine]:
        character_count = len(self.characters)
        first_index = self._conversation_index % character_count
        second_index = (first_index + 1) % character_count
        first = self.characters[first_index]
        second = self.characters[second_index]
        prompt, reply = self._conversations[
            self._conversation_index % len(self._conversations)
        ]
        self._conversation_index += 1
        return DialogueLine(first.name, prompt), DialogueLine(second.name, reply)

    def reply_to_user(self, message: str) -> DialogueLine:
        text = " ".join(message.split())
        if not text:
            raise ValueError("Mesaj boş olamaz.")

        normalized = text.casefold()
        if any(word in normalized for word in ("merhaba", "selam", "hello")):
            reply = "Merhaba! Ben DemoPHO. Demo Keon'un yerel sohbet demosundayız."
        elif any(word in normalized for word in ("linux", "işletim sistemi", "sistem")):
            reply = (
                "Demo Keon Linux konuk sistemi olarak tasarlanıyor. "
                "Wox henüz Linux ISO'su başlatamıyor."
            )
        elif "demo keon" in normalized or "demopho" in normalized:
            reply = "Demo Keon ve DemoPHO bu yerel prototipte birlikte gelişiyor."
        else:
            excerpt = text[:80]
            if len(text) > 80:
                excerpt += "..."
            reply = (
                f"Mesajını aldım: “{excerpt}” "
                "Bu sürüm çevrimdışı bir sohbet prototipidir."
            )
        return DialogueLine("DemoPHO", reply)
