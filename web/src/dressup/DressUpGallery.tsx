// Dev-only QA gallery: render the figure wearing every option of each slot so
// alignment/fit can be screenshot-verified. Reachable at ?dressupgallery.
import Figure from "./Figure";
import {
  type Member, defaultMember,
  HAIR, HATS, GLASSES, TOPS, BOTTOMS, SHOES, ACCESSORIES, HAIR_COLORS,
} from "./wardrobe";

function Row({ title, make }: { title: string; make: () => { label: string; m: Member }[] }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ color: "#9aa", fontSize: 13, margin: "4px 0", fontWeight: 700 }}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {make().map(({ label, m }, i) => (
          <div key={i} style={{ textAlign: "center", background: "#15151c", borderRadius: 8, padding: 4 }}>
            <Figure member={m} size={84} />
            <div style={{ fontSize: 10, color: "#bbb" }}>{label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DressUpGallery() {
  const base = (): Member => ({ ...defaultMember("Vocals", "Test"), hairColor: "h-brown" });
  return (
    <div style={{ padding: 16, background: "#0c0c11", minHeight: "100vh" }}>
      <h2 style={{ color: "#eee" }}>Dress-up fit gallery</h2>
      <Row title="Body" make={() => [
        { label: "girl · tee", m: { ...base(), body: "girl" as const } },
        { label: "boy · tee", m: { ...base(), body: "boy" as const } },
        { label: "girl · dress", m: { ...base(), body: "girl" as const, top: "dress", topColor: "pink", bottom: "none", hair: "long" } },
        { label: "boy · jacket", m: { ...base(), body: "boy" as const, top: "jacket", topColor: "gray", hair: "spiky", hat: "ears", hatColor: "gray" } },
      ]} />
      <Row title="Hair" make={() => HAIR.map((s) => ({ label: s.name, m: { ...base(), hair: s.id } }))} />
      <Row title="Hair color" make={() => HAIR_COLORS.map((s) => ({ label: s.name, m: { ...base(), hair: "long", hairColor: s.id } }))} />
      <Row title="Hats" make={() => HATS.map((s) => ({ label: s.name, m: { ...base(), hat: s.id, hatColor: "pink" } }))} />
      <Row title="Glasses" make={() => GLASSES.map((s) => ({ label: s.name, m: { ...base(), glasses: s.id } }))} />
      <Row title="Tops" make={() => TOPS.map((s) => ({ label: s.name, m: { ...base(), top: s.id, topColor: "coral", bottom: s.id === "dress" || s.id === "gown" ? "none" : "pants" } }))} />
      <Row title="Bottoms" make={() => BOTTOMS.filter((s) => s.id !== "none").map((s) => ({ label: s.name, m: { ...base(), bottom: s.id, bottomColor: "indigo" } }))} />
      <Row title="Shoes" make={() => SHOES.map((s) => ({ label: s.name, m: { ...base(), shoes: s.id, shoesColor: "red" } }))} />
      <Row title="Accessories" make={() => ACCESSORIES.map((s) => ({ label: s.name, m: { ...base(), accessory: s.id, accessoryColor: "purple" } }))} />
    </div>
  );
}
