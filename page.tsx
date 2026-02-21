import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Leaf,
  Factory,
  Gauge,
  ShieldCheck,
  LineChart,
  Sparkles,
  Phone,
  Mail,
  MapPin,
  Check,
  ArrowRight,
  Calculator,
  Zap,
  Droplets,
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

/**
 * Bio Gaz Startup uchun zamonaviy, qulay, soft (glass + gentle) UI landing.
 * 
 * Ishlatish (tez):
 * 1) Next.js + Tailwind loyihaga qo‘shing.
 * 2) `npm i framer-motion lucide-react recharts`
 * 3) Bu komponentni `app/page.tsx` (yoki .jsx) ichida render qiling.
 * 
 * Eslatma: Kontakt form submit qismi demo (backendga ulanmagan).
 */

// -----------------------
// Tiny UI primitives (standalone, shadcn talab qilmaydi)
// -----------------------
function cn(...a) {
  return a.filter(Boolean).join(" ");
}

function Button({
  children,
  className,
  variant = "primary",
  size = "md",
  ...props
}) {
  const base =
    "inline-flex items-center justify-center rounded-2xl font-medium transition active:scale-[0.99] focus:outline-none focus-visible:ring-2 focus-visible:ring-black/10";
  const variants = {
    primary:
      "bg-black text-white hover:bg-black/90 shadow-[0_16px_40px_-18px_rgba(0,0,0,0.55)]",
    soft:
      "bg-white/70 text-black hover:bg-white/90 border border-black/5 shadow-[0_18px_50px_-24px_rgba(0,0,0,0.35)] backdrop-blur",
    ghost: "bg-transparent text-black hover:bg-black/5",
  };
  const sizes = {
    md: "h-11 px-5 text-[15px]",
    sm: "h-10 px-4 text-[14px]",
    lg: "h-12 px-6 text-[15px]",
  };
  return (
    <button
      className={cn(base, variants[variant], sizes[size], className)}
      {...props}
    >
      {children}
    </button>
  );
}

function Card({ children, className }) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-black/5 bg-white/70 backdrop-blur shadow-[0_18px_70px_-40px_rgba(0,0,0,0.35)]",
        className
      )}
    >
      {children}
    </div>
  );
}

function Badge({ children, className }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border border-black/5 bg-white/70 px-3 py-1 text-xs text-black/80 backdrop-blur",
        className
      )}
    >
      {children}
    </span>
  );
}

function Input({ className, ...props }) {
  return (
    <input
      className={cn(
        "h-11 w-full rounded-2xl border border-black/10 bg-white/75 px-4 text-[15px] outline-none placeholder:text-black/35 focus:border-black/20 focus:ring-2 focus:ring-black/5",
        className
      )}
      {...props}
    />
  );
}

function Select({ className, children, ...props }) {
  return (
    <select
      className={cn(
        "h-11 w-full rounded-2xl border border-black/10 bg-white/75 px-4 text-[15px] outline-none focus:border-black/20 focus:ring-2 focus:ring-black/5",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

function Textarea({ className, ...props }) {
  return (
    <textarea
      className={cn(
        "min-h-[110px] w-full resize-none rounded-2xl border border-black/10 bg-white/75 px-4 py-3 text-[15px] outline-none placeholder:text-black/35 focus:border-black/20 focus:ring-2 focus:ring-black/5",
        className
      )}
      {...props}
    />
  );
}

function SectionTitle({ eyebrow, title, subtitle }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      {eyebrow ? (
        <div className="mb-3 flex items-center justify-center">
          <Badge>
            <Sparkles className="h-3.5 w-3.5" />
            {eyebrow}
          </Badge>
        </div>
      ) : null}
      <h2 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl">
        {title}
      </h2>
      {subtitle ? (
        <p className="mt-3 text-pretty text-base text-black/60 sm:text-[17px]">
          {subtitle}
        </p>
      ) : null}
    </div>
  );
}

function Divider() {
  return <div className="my-10 h-px w-full bg-black/5" />;
}

function useSmoothScroll() {
  return (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    const y = el.getBoundingClientRect().top + window.scrollY - 90;
    window.scrollTo({ top: y, behavior: "smooth" });
  };
}

// -----------------------
// Calculator (demo model)
// -----------------------
const FEEDSTOCK = [
  { key: "cattle", label: "Qoramol go‘ngi", factor_m3_per_kg: 0.03 },
  { key: "poultry", label: "Parranda go‘ngi", factor_m3_per_kg: 0.06 },
  { key: "food", label: "Oziq-ovqat chiqindisi", factor_m3_per_kg: 0.09 },
  { key: "mixed", label: "Aralash organik", factor_m3_per_kg: 0.05 },
];

function estimate({ feedstockKey, kgPerDay, gasPriceUZS = 1800, electricityPriceUZS = 450 }) {
  const fs = FEEDSTOCK.find((x) => x.key === feedstockKey) ?? FEEDSTOCK[0];
  const biogas_m3 = Math.max(0, kgPerDay) * fs.factor_m3_per_kg;

  // Rough energy equivalents (demo): 1 m3 biogas ≈ 6 kWh thermal, electrical via generator ~ 2 kWh
  const thermal_kwh = biogas_m3 * 6;
  const electric_kwh = biogas_m3 * 2;

  // Monthly savings estimation (demo): assume replacing gas + part electricity
  const monthly_saving =
    (biogas_m3 * gasPriceUZS + electric_kwh * electricityPriceUZS) * 30;

  // Simple capex suggestion (demo) based on output
  const capex = Math.max(12_000_000, biogas_m3 * 1_200_000); // UZS

  const payback_months = monthly_saving > 0 ? capex / monthly_saving : Infinity;

  // CO2e reduction (very rough)
  const co2_kg_per_day = biogas_m3 * 1.9; // demo

  return {
    feedstock: fs.label,
    biogas_m3: round(biogas_m3, 2),
    thermal_kwh: round(thermal_kwh, 1),
    electric_kwh: round(electric_kwh, 1),
    monthly_saving: Math.round(monthly_saving),
    capex: Math.round(capex),
    payback_months: payback_months === Infinity ? null : round(payback_months, 1),
    co2_kg_per_day: round(co2_kg_per_day, 1),
  };
}

function round(x, d = 2) {
  const p = 10 ** d;
  return Math.round(x * p) / p;
}

function moneyUZS(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("uz-UZ").format(n) + " so‘m";
}

// -----------------------
// Data
// -----------------------
const NAV = [
  { id: "solution", label: "YeChim" },
  { id: "how", label: "Qanday ishlaydi" },
  { id: "calc", label: "Hisob-kitob" },
  { id: "cases", label: "Loyihalar" },
  { id: "pricing", label: "Paketlar" },
  { id: "faq", label: "FAQ" },
  { id: "contact", label: "Kontakt" },
];

const FEATURES = [
  {
    icon: Leaf,
    title: "Ekologik va foydali",
    desc: "Chiqindini resursga aylantirib, hid va ifloslanishni kamaytiradi.",
  },
  {
    icon: Gauge,
    title: "Tejamkor energiya",
    desc: "Gaz/electric xarajatlarni sezilarli qisqartirish uchun optimallashtirilgan.",
  },
  {
    icon: ShieldCheck,
    title: "Xavfsizlik + monitoring",
    desc: "Bosim, harorat va tizim holati bo‘yicha doimiy nazorat (demo).",
  },
  {
    icon: Factory,
    title: "Ferma va korxonalar",
    desc: "Qoramol/parranda fermasi, oshxona, zavodlar uchun mos modullar.",
  },
];

const STEPS = [
  {
    step: "01",
    title: "Xomashyo yig‘ish",
    desc: "Go‘ng va organik chiqindilar xavfsiz konteynerlarda yig‘iladi.",
    icon: Droplets,
  },
  {
    step: "02",
    title: "Fermentatsiya",
    desc: "Anaerob reaktorda biologik parchalanish orqali biogaz hosil bo‘ladi.",
    icon: Leaf,
  },
  {
    step: "03",
    title: "Gazni tozalash & saqlash",
    desc: "Namlik va aralashmalar kamaytirilib, tizim barqaror ishlaydi.",
    icon: ShieldCheck,
  },
  {
    step: "04",
    title: "Energiya & o‘g‘it",
    desc: "Gaz/electric va digestat (organik o‘g‘it) hosil bo‘ladi.",
    icon: Zap,
  },
];

const CASES = [
  {
    place: "Farg‘ona",
    title: "200 bosh qoramol fermasi",
    result: "Kuniga 180–220 m³ biogaz (demo)",
    tags: ["Tejamkor", "Hid kamaydi", "O‘g‘it"],
  },
  {
    place: "Toshkent",
    title: "Oziq-ovqat chiqindisi — kichik korxona",
    result: "Kuniga 40–60 m³ biogaz (demo)",
    tags: ["24/7 monitoring", "Modul"],
  },
  {
    place: "Samarqand",
    title: "Aralash organik — issiqxona",
    result: "Qishda ham barqaror ishlash (demo)",
    tags: ["Isitish", "ROI"],
  },
];

const PRICING = [
  {
    name: "Starter",
    price: "Kichik hajm",
    bullets: [
      "Mini reaktor (demo)",
      "Bazaviy xavfsizlik",
      "O‘rnatish bo‘yicha yo‘riqnoma",
      "1 oylik servis",
    ],
    accent: false,
  },
  {
    name: "Standard",
    price: "Eng mashhur",
    bullets: [
      "O‘rtacha quvvat",
      "Gaz tozalash moduli",
      "Sensorlar + monitoring (demo)",
      "3 oylik servis",
    ],
    accent: true,
  },
  {
    name: "Pro",
    price: "Korxona darajasi",
    bullets: [
      "Katta quvvat",
      "Generator integratsiyasi (ixtiyoriy)",
      "Remote dashboard (demo)",
      "12 oylik servis",
    ],
    accent: false,
  },
];

const FAQ = [
  {
    q: "Hid bo‘ladimi?",
    a: "To‘g‘ri yig‘ish va yopiq reaktor bo‘lsa, hid sezilarli kamayadi. Montaj va servis talablari muhim.",
  },
  {
    q: "Qishda ham ishlaydimi?",
    a: "Ha, lekin haroratni ushlab turish (izolyatsiya/isitish) tizim barqarorligiga ta’sir qiladi.",
  },
  {
    q: "Xavfsizlik qanday ta’minlanadi?",
    a: "Bosim va oqish nazorati, xavfsizlik klapanlari, muntazam texnik ko‘rik (paketga qarab).",
  },
  {
    q: "O‘g‘it sifatida foydasi bormi?",
    a: "Digestat organik o‘g‘it sifatida ishlatiladi. Amaliy natija xomashyo va jarayonga bog‘liq.",
  },
];

// -----------------------
// Main Component
// -----------------------
export default function BioGazStartupLanding() {
  const scrollTo = useSmoothScroll();

  const [calc, setCalc] = useState({
    feedstockKey: "cattle",
    kgPerDay: 600,
    gasPriceUZS: 1800,
    electricityPriceUZS: 450,
  });

  const result = useMemo(() => estimate(calc), [calc]);

  const chartData = useMemo(() => {
    // Demo 12 months cashflow based on savings
    const capex = result.capex || 0;
    const m = result.monthly_saving || 0;
    let cum = -capex;
    return Array.from({ length: 12 }, (_, i) => {
      cum += m;
      return { month: i + 1, cum: Math.round(cum) };
    });
  }, [result.capex, result.monthly_saving]);

  const [faqOpen, setFaqOpen] = useState(0);
  const [toast, setToast] = useState(null);

  function notify(msg) {
    setToast(msg);
    window.clearTimeout(notify._t);
    notify._t = window.setTimeout(() => setToast(null), 2200);
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(1000px_600px_at_20%_0%,rgba(34,197,94,0.20),transparent_60%),radial-gradient(900px_560px_at_80%_10%,rgba(59,130,246,0.18),transparent_55%),radial-gradient(900px_560px_at_50%_100%,rgba(99,102,241,0.12),transparent_60%)]">
      {/* Top glow */}
      <div className="pointer-events-none fixed inset-0 opacity-60">
        <div className="absolute left-[-200px] top-[-220px] h-[520px] w-[520px] rounded-full bg-black/5 blur-3xl" />
        <div className="absolute right-[-260px] top-[-260px] h-[620px] w-[620px] rounded-full bg-black/5 blur-3xl" />
      </div>

      {/* Toast */}
      {toast ? (
        <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
          <div className="rounded-2xl border border-black/10 bg-white/85 px-4 py-2 text-sm shadow-[0_20px_60px_-30px_rgba(0,0,0,0.45)] backdrop-blur">
            {toast}
          </div>
        </div>
      ) : null}

      {/* Navbar */}
      <header className="sticky top-0 z-40 border-b border-black/5 bg-white/55 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <button
            onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
            className="flex items-center gap-2 rounded-2xl px-2 py-1 hover:bg-black/5"
          >
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-black text-white shadow-[0_18px_60px_-40px_rgba(0,0,0,0.6)]">
              <Leaf className="h-5 w-5" />
            </div>
            <div className="text-left leading-tight">
              <div className="text-[15px] font-semibold">Bio Gaz</div>
              <div className="text-xs text-black/50">Green-energy platform</div>
            </div>
          </button>

          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => scrollTo(n.id)}
                className="rounded-2xl px-3 py-2 text-sm text-black/70 hover:bg-black/5 hover:text-black"
              >
                {n.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-2">
            <Button
              variant="soft"
              className="hidden sm:inline-flex"
              onClick={() => {
                scrollTo("contact");
                notify("Kontakt bo‘limiga o‘tdik ✅");
              }}
            >
              Bepul konsultatsiya
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button
              onClick={() => {
                scrollTo("calc");
                notify("Hisob-kitobga o‘tdik 🧮");
              }}
            >
              Hisob-kitob
              <Calculator className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

      {/* Hero */}
      <main className="mx-auto max-w-6xl px-4 pb-20 pt-10 sm:px-6 sm:pt-14">
        <div className="grid gap-8 lg:grid-cols-2 lg:items-center">
          <div>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <Badge>
                <LineChart className="h-3.5 w-3.5" />
                Respublika bosqichi uchun pitch-ready
              </Badge>
              <Badge>
                <ShieldCheck className="h-3.5 w-3.5" />
                Soft UI • tez yuklanadi
              </Badge>
            </div>

            <motion.h1
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="text-balance text-4xl font-semibold tracking-tight sm:text-5xl"
            >
              Chiqindini energiyaga aylantiring —
              <span className="text-black/70"> gaz, elektr va o‘g‘it</span> bitta tizimda.
            </motion.h1>

            <p className="mt-4 text-pretty text-base text-black/60 sm:text-[17px]">
              Bio Gaz — fermerlar va korxonalar uchun zamonaviy biogaz yechimi.
              Xarajatlarni kamaytiring, ekologiyani yaxshilang, jarayonni monitoring qiling.
            </p>

            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Button
                size="lg"
                onClick={() => {
                  scrollTo("contact");
                  notify("Ariza qoldirishga o‘tdik ✍️");
                }}
              >
                Ariza qoldirish
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
              <Button
                size="lg"
                variant="soft"
                onClick={() => {
                  scrollTo("cases");
                  notify("Loyihalar bo‘limi ✅");
                }}
              >
                Real natijalar (demo)
                <Check className="ml-2 h-4 w-4" />
              </Button>
            </div>

            <div className="mt-7 grid gap-3 sm:grid-cols-3">
              <Stat k="Tez o‘rnatish" v="7–21 kun" sub="loyiha turiga qarab" />
              <Stat k="Tejamkor" v="−20%…−60%" sub="xarajat kamayishi" />
              <Stat k="Monitoring" v="24/7" sub="sensorlar (demo)" />
            </div>

            <div className="mt-7 flex flex-wrap items-center gap-3 text-sm text-black/60">
              <span className="inline-flex items-center gap-2">
                <Phone className="h-4 w-4" /> +998 XX XXX XX XX
              </span>
              <span className="hidden sm:inline">•</span>
              <span className="inline-flex items-center gap-2">
                <Mail className="h-4 w-4" /> info@biogaz.uz
              </span>
            </div>
          </div>

          <div>
            <Card className="relative overflow-hidden p-5 sm:p-6">
              <div className="absolute -right-14 -top-14 h-56 w-56 rounded-full bg-black/5 blur-2xl" />
              <div className="absolute -bottom-16 -left-16 h-64 w-64 rounded-full bg-black/5 blur-2xl" />

              <div className="relative">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">Dashboard preview</div>
                    <div className="mt-1 text-xs text-black/50">
                      Tez ko‘rinish: ishlab chiqarish, tejamkorlik, ROI
                    </div>
                  </div>
                  <Badge className="text-[11px]">Live demo</Badge>
                </div>

                <Divider />

                <div className="grid gap-3 sm:grid-cols-3">
                  <MiniKpi title="Biogaz" value={`${result.biogas_m3} m³/kun`} icon={Droplets} />
                  <MiniKpi title="Elektr" value={`${result.electric_kwh} kWh/kun`} icon={Zap} />
                  <MiniKpi
                    title="Tejam"
                    value={moneyUZS(result.monthly_saving)}
                    icon={LineChart}
                  />
                </div>

                <div className="mt-5 rounded-3xl border border-black/5 bg-white/60 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <div className="text-sm font-semibold">Kumulyativ cashflow (12 oy)</div>
                    <div className="text-xs text-black/50">demo hisob</div>
                  </div>
                  <div className="h-44 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}>
                        <defs>
                          <linearGradient id="c" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="currentColor" stopOpacity={0.18} />
                            <stop offset="95%" stopColor="currentColor" stopOpacity={0.02} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
                        <XAxis dataKey="month" tick={{ fontSize: 12, fill: "rgba(0,0,0,0.55)" }} />
                        <YAxis tick={{ fontSize: 12, fill: "rgba(0,0,0,0.55)" }} />
                        <Tooltip
                          contentStyle={{
                            borderRadius: 14,
                            border: "1px solid rgba(0,0,0,0.08)",
                            background: "rgba(255,255,255,0.9)",
                            backdropFilter: "blur(10px)",
                          }}
                          formatter={(v) => [moneyUZS(v), "Kumulyativ"]}
                          labelFormatter={(l) => `${l}-oy`}
                        />
                        <Area
                          type="monotone"
                          dataKey="cum"
                          stroke="currentColor"
                          fill="url(#c)"
                          strokeWidth={2}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Badge>
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Kafolat va servis
                  </Badge>
                  <Badge>
                    <Leaf className="h-3.5 w-3.5" />
                    Eco-impact: {result.co2_kg_per_day} kg CO₂/kun (demo)
                  </Badge>
                </div>
              </div>
            </Card>
          </div>
        </div>

        {/* Solution */}
        <section id="solution" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Yechim"
            title="Bio Gaz — real muammolar uchun real natija"
            subtitle="Startup taqdimoti uchun: foyda, raqamlar, vizual ishonch. Bu sahifa keyin ham savdo/lead uchun ishlaydi."
          />

          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f) => (
              <Card key={f.title} className="p-5">
                <div className="flex items-start gap-3">
                  <div className="grid h-11 w-11 place-items-center rounded-2xl bg-black text-white">
                    <f.icon className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="text-[15px] font-semibold">{f.title}</div>
                    <div className="mt-1 text-sm text-black/60">{f.desc}</div>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          <div className="mt-6 grid gap-4 lg:grid-cols-3">
            <Card className="p-6 lg:col-span-2">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold">Nega aynan hozir?</div>
                  <p className="mt-2 text-sm text-black/60">
                    Energiya narxlari va ekologik talablar oshib boryapti. Biogaz tizimi —
                    chiqindini kamaytirib, energiya ishlab chiqaradigan "win-win" model.
                  </p>
                </div>
                <Badge className="hidden sm:inline-flex">Strategy</Badge>
              </div>
              <Divider />
              <ul className="grid gap-3 sm:grid-cols-2">
                <Bullet>O‘zini oqlash (ROI)ni kalkulyatorda ko‘ring</Bullet>
                <Bullet>Servis va xavfsizlik protokollari</Bullet>
                <Bullet>Modulli tizim — keyin kengaytirish mumkin</Bullet>
                <Bullet>Organik o‘g‘it: qo‘shimcha qiymat</Bullet>
              </ul>
            </Card>
            <Card className="p-6">
              <div className="text-sm font-semibold">Pitch uchun 3 asosiy tezis</div>
              <div className="mt-3 space-y-3">
                <PitchItem n="1" t="Tejamkor" d="Energiya xarajati kamayadi" />
                <PitchItem n="2" t="Ekologik" d="Chiqindi va hid pasayadi" />
                <PitchItem n="3" t="Monitoring" d="Jarayon nazoratda (demo)" />
              </div>
            </Card>
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Jarayon"
            title="Qanday ishlaydi"
            subtitle="Oddiy, tushunarli, hakamlar uchun ham aniq. Har bosqichda xavfsizlik va samaradorlik." 
          />

          <div className="mt-10 grid gap-4 lg:grid-cols-4">
            {STEPS.map((s) => (
              <motion.div
                key={s.step}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.4 }}
              >
                <Card className="h-full p-5">
                  <div className="flex items-center justify-between">
                    <div className="text-xs font-semibold text-black/45">{s.step}</div>
                    <div className="grid h-10 w-10 place-items-center rounded-2xl bg-black text-white">
                      <s.icon className="h-5 w-5" />
                    </div>
                  </div>
                  <div className="mt-4 text-[15px] font-semibold">{s.title}</div>
                  <div className="mt-1 text-sm text-black/60">{s.desc}</div>
                </Card>
              </motion.div>
            ))}
          </div>
        </section>

        {/* Calculator */}
        <section id="calc" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Hisob-kitob"
            title="1 daqiqada ROI va ishlab chiqarishni hisoblang"
            subtitle="Raqamlar — eng kuchli ishonch. Bu demo model, real loyihada joyida audit bilan aniqlashtiriladi." 
          />

          <div className="mt-10 grid gap-4 lg:grid-cols-5">
            <Card className="p-6 lg:col-span-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Parametrlar</div>
                <Badge className="text-[11px]">Demo kalkulyator</Badge>
              </div>
              <Divider />

              <div className="space-y-4">
                <div>
                  <div className="mb-2 text-sm font-medium text-black/70">Xomashyo turi</div>
                  <Select
                    value={calc.feedstockKey}
                    onChange={(e) => setCalc((p) => ({ ...p, feedstockKey: e.target.value }))}
                  >
                    {FEEDSTOCK.map((x) => (
                      <option key={x.key} value={x.key}>
                        {x.label}
                      </option>
                    ))}
                  </Select>
                </div>

                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <div className="text-sm font-medium text-black/70">Kunlik hajm (kg/kun)</div>
                    <div className="text-xs text-black/45">tavsiya: 200–2000</div>
                  </div>
                  <Input
                    type="number"
                    value={calc.kgPerDay}
                    onChange={(e) => setCalc((p) => ({ ...p, kgPerDay: Number(e.target.value) }))}
                    placeholder="Masalan: 600"
                    min={0}
                  />
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Gaz narxi (so‘m)</div>
                    <Input
                      type="number"
                      value={calc.gasPriceUZS}
                      onChange={(e) =>
                        setCalc((p) => ({ ...p, gasPriceUZS: Number(e.target.value) }))
                      }
                      min={0}
                    />
                  </div>
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Elektr narxi (so‘m)</div>
                    <Input
                      type="number"
                      value={calc.electricityPriceUZS}
                      onChange={(e) =>
                        setCalc((p) => ({ ...p, electricityPriceUZS: Number(e.target.value) }))
                      }
                      min={0}
                    />
                  </div>
                </div>

                <Button
                  variant="soft"
                  onClick={() => notify("Natijalar yangilandi ✅")}
                  className="w-full"
                >
                  Natijani yangilash
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>

                <p className="text-xs leading-relaxed text-black/50">
                  * Bu kalkulyator demo. Respublika bosqichi uchun tushunarli ko‘rsatkich berish maqsadida.
                  Real loyiha: xomashyo tarkibi, harorat, reaktor hajmi va generator samaradorligi bilan aniqlanadi.
                </p>
              </div>
            </Card>

            <Card className="p-6 lg:col-span-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Natijalar</div>
                <Badge className="text-[11px]">{result.feedstock}</Badge>
              </div>
              <Divider />

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <ResultTile label="Biogaz" value={`${result.biogas_m3} m³/kun`} hint="taxmin" icon={Droplets} />
                <ResultTile label="Issiqlik" value={`${result.thermal_kwh} kWh/kun`} hint="ekvivalent" icon={Zap} />
                <ResultTile label="Elektr" value={`${result.electric_kwh} kWh/kun`} hint="generator bilan" icon={Zap} />
                <ResultTile label="Oyiga tejam" value={moneyUZS(result.monthly_saving)} hint="taxmin" icon={LineChart} />
                <ResultTile label="CAPEX" value={moneyUZS(result.capex)} hint="demo" icon={Factory} />
                <ResultTile
                  label="Payback"
                  value={result.payback_months ? `${result.payback_months} oy` : "—"}
                  hint="taxmin"
                  icon={Gauge}
                />
              </div>

              <div className="mt-5 rounded-3xl border border-black/5 bg-white/60 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold">Eco-impact</div>
                    <div className="mt-1 text-xs text-black/50">
                      Taxminiy CO₂ kamayishi (demo)
                    </div>
                  </div>
                  <Badge>
                    <Leaf className="h-3.5 w-3.5" /> {result.co2_kg_per_day} kg/kun
                  </Badge>
                </div>
                <div className="mt-3 text-sm text-black/60">
                  Chiqindilarni qayta ishlash va biogazdan foydalanish — emissiyani kamaytirishga yordam beradi.
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    variant="soft"
                    onClick={() => {
                      const text =
                        `Bio Gaz hisob-kitob (demo)\n` +
                        `Xomashyo: ${result.feedstock}\n` +
                        `Biogaz: ${result.biogas_m3} m³/kun\n` +
                        `Elektr: ${result.electric_kwh} kWh/kun\n` +
                        `Oyiga tejam: ${moneyUZS(result.monthly_saving)}\n` +
                        `Payback: ${result.payback_months ? result.payback_months + " oy" : "—"}`;
                      navigator.clipboard?.writeText(text);
                      notify("Natija clipboard’ga nusxalandi 📋");
                    }}
                  >
                    Natijani nusxalash
                  </Button>
                  <Button
                    onClick={() => {
                      scrollTo("contact");
                      notify("Natijani yuborish uchun kontaktga o‘tdik 📩");
                    }}
                  >
                    Natijani yuborish
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </div>
            </Card>
          </div>
        </section>

        {/* Cases */}
        <section id="cases" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Loyihalar"
            title="Case studies (demo)"
            subtitle="Sizning haqiqiy loyihalaringiz bilan to‘ldirish oson: 3–6 ta case yetarli. Bu bo‘lim hakamlar uchun ishonch beradi." 
          />
          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            {CASES.map((c) => (
              <Card key={c.title} className="p-6">
                <div className="flex items-center justify-between">
                  <div className="text-xs font-semibold text-black/45">{c.place}</div>
                  <Badge className="text-[11px]">Case</Badge>
                </div>
                <div className="mt-3 text-[15px] font-semibold">{c.title}</div>
                <div className="mt-1 text-sm text-black/60">{c.result}</div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {c.tags.map((t) => (
                    <Badge key={t} className="text-[11px]">
                      {t}
                    </Badge>
                  ))}
                </div>
                <Divider />
                <Button
                  variant="soft"
                  className="w-full"
                  onClick={() => {
                    scrollTo("contact");
                    notify("Case bo‘yicha demo ariza ✅");
                  }}
                >
                  Shu formatda loyiha xohlayman
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </Card>
            ))}
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Paketlar"
            title="Oddiy narxlash va aniq qiymat"
            subtitle="Respublika bosqichida yaxshi ko‘rinadi: paketlar, kafolat, servis. Narxni keyin real auditdan keyin yozishingiz mumkin." 
          />

          <div className="mt-10 grid gap-4 lg:grid-cols-3">
            {PRICING.map((p) => (
              <Card
                key={p.name}
                className={cn(
                  "p-6",
                  p.accent && "border-black/10 bg-white/80 shadow-[0_28px_90px_-50px_rgba(0,0,0,0.55)]"
                )}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-lg font-semibold">{p.name}</div>
                    <div className="mt-1 text-sm text-black/60">{p.price}</div>
                  </div>
                  {p.accent ? <Badge>Recommended</Badge> : <Badge className="opacity-70">Plan</Badge>}
                </div>
                <Divider />
                <ul className="space-y-3">
                  {p.bullets.map((b) => (
                    <li key={b} className="flex items-start gap-2 text-sm text-black/70">
                      <span className="mt-0.5 grid h-5 w-5 place-items-center rounded-full bg-black text-white">
                        <Check className="h-3.5 w-3.5" />
                      </span>
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
                <div className="mt-6">
                  <Button
                    className="w-full"
                    variant={p.accent ? "primary" : "soft"}
                    onClick={() => {
                      scrollTo("contact");
                      notify(`${p.name} paketi bo‘yicha ariza ✍️`);
                    }}
                  >
                    Ariza qoldirish
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Savol-javob"
            title="Ko‘p beriladigan savollar"
            subtitle="Hakamlar va mijozlar bir xil savol beradi. Bu bo‘lim ishonchni oshiradi." 
          />

          <div className="mt-10 grid gap-4 lg:grid-cols-2">
            <Card className="p-6">
              <div className="text-sm font-semibold">FAQ</div>
              <Divider />
              <div className="space-y-2">
                {FAQ.map((x, i) => {
                  const open = i === faqOpen;
                  return (
                    <div key={x.q} className="rounded-2xl border border-black/5 bg-white/60">
                      <button
                        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                        onClick={() => setFaqOpen(open ? -1 : i)}
                      >
                        <div className="text-sm font-medium">{x.q}</div>
                        <div className={cn("text-xs text-black/45 transition", open && "rotate-180")}>
                          ▼
                        </div>
                      </button>
                      {open ? (
                        <div className="px-4 pb-4 text-sm text-black/60">{x.a}</div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </Card>

            <Card className="p-6">
              <div className="text-sm font-semibold">Startup checklist (pitch)</div>
              <Divider />
              <ul className="space-y-3 text-sm text-black/70">
                <li className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4" />
                  Muammo → yechim → natija (1 slaydda ham tushunarli)
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4" />
                  Raqamlar: m³/kWh/ROI (kalkulyator bilan)
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4" />
                  Case studies va vizual dalil
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4" />
                  Paketlar, servis, kafolat
                </li>
                <li className="flex gap-2">
                  <Check className="mt-0.5 h-4 w-4" />
                  CTA: ariza, telefon, Telegram/WhatsApp
                </li>
              </ul>
              <div className="mt-6">
                <Button
                  variant="soft"
                  className="w-full"
                  onClick={() => {
                    notify("Checklist nusxa olish: demo")
                    const text =
                      "Bio Gaz pitch checklist:\n" +
                      "- Muammo→Yechim→Natija\n" +
                      "- Raqamlar: m³/kWh/ROI\n" +
                      "- Case studies\n" +
                      "- Paket/Servis/Kafolat\n" +
                      "- CTA: ariza + aloqa";
                    navigator.clipboard?.writeText(text);
                  }}
                >
                  Checklist’ni nusxalash
                </Button>
              </div>
            </Card>
          </div>
        </section>

        {/* Contact */}
        <section id="contact" className="mt-16 scroll-mt-24">
          <SectionTitle
            eyebrow="Kontakt"
            title="Bepul audit va konsultatsiya"
            subtitle="Kontakt formni 30 soniyada to‘ldiring — sizga mos quvvat va konfiguratsiya tavsiya qilamiz." 
          />

          <div className="mt-10 grid gap-4 lg:grid-cols-5">
            <Card className="p-6 lg:col-span-2">
              <div className="text-sm font-semibold">Aloqa</div>
              <Divider />

              <div className="space-y-3 text-sm text-black/70">
                <InfoRow icon={Phone} label="Telefon" value="+998 XX XXX XX XX" />
                <InfoRow icon={Mail} label="Email" value="info@biogaz.uz" />
                <InfoRow icon={MapPin} label="Manzil" value="Toshkent, O‘zbekiston" />
              </div>

              <Divider />

              <div className="space-y-2">
                <Button
                  className="w-full"
                  onClick={() => {
                    navigator.clipboard?.writeText("+998 XX XXX XX XX");
                    notify("Telefon raqami nusxalandi 📞");
                  }}
                >
                  Telefonni nusxalash
                </Button>
                <Button
                  variant="soft"
                  className="w-full"
                  onClick={() => notify("Telegram/WhatsApp linklarini qo‘shib beramiz ✅")}
                >
                  Telegram / WhatsApp
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              </div>

              <p className="mt-4 text-xs text-black/50">
                * Real loyihada bu yerga QR-kod, ijtimoiy tarmoqlar, sertifikatlar va hamkor logotiplari qo‘shiladi.
              </p>
            </Card>

            <Card className="p-6 lg:col-span-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold">Ariza formasi</div>
                <Badge className="text-[11px]">30 soniya</Badge>
              </div>
              <Divider />

              <form
                className="grid gap-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  notify("Ariza yuborildi (demo) ✅");
                }}
              >
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Ism</div>
                    <Input placeholder="Ismingiz" required />
                  </div>
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Telefon</div>
                    <Input placeholder="+998 ..." required />
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Shahar/region</div>
                    <Input placeholder="Masalan: Samarqand" required />
                  </div>
                  <div>
                    <div className="mb-2 text-sm font-medium text-black/70">Faoliyat</div>
                    <Select defaultValue="farm">
                      <option value="farm">Ferma</option>
                      <option value="factory">Korxona</option>
                      <option value="food">Oziq-ovqat / oshxona</option>
                      <option value="other">Boshqa</option>
                    </Select>
                  </div>
                </div>

                <div>
                  <div className="mb-2 text-sm font-medium text-black/70">Qisqa izoh</div>
                  <Textarea placeholder="Masalan: 150 bosh qoramol, go‘ng ~ 500 kg/kun" />
                </div>

                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="text-xs text-black/50">
                    Yuborish orqali siz aloqa uchun rozilik bildirasiz.
                  </div>
                  <Button type="submit">
                    Yuborish
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </form>
            </Card>
          </div>
        </section>

        {/* Footer */}
        <footer className="mt-16 border-t border-black/5 pb-10 pt-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-sm text-black/60">© {new Date().getFullYear()} Bio Gaz. All rights reserved.</div>
            <div className="flex flex-wrap items-center gap-2">
              {NAV.map((n) => (
                <button
                  key={n.id}
                  onClick={() => scrollTo(n.id)}
                  className="rounded-2xl px-3 py-2 text-sm text-black/60 hover:bg-black/5 hover:text-black"
                >
                  {n.label}
                </button>
              ))}
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

// -----------------------
// Small components
// -----------------------
function Stat({ k, v, sub }) {
  return (
    <Card className="p-4">
      <div className="text-xs font-semibold text-black/45">{k}</div>
      <div className="mt-1 text-xl font-semibold">{v}</div>
      <div className="mt-1 text-xs text-black/50">{sub}</div>
    </Card>
  );
}

function MiniKpi({ title, value, icon: Icon }) {
  return (
    <div className="rounded-3xl border border-black/5 bg-white/60 p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-black/45">{title}</div>
        <Icon className="h-4 w-4 text-black/60" />
      </div>
      <div className="mt-2 text-sm font-semibold">{value}</div>
    </div>
  );
}

function Bullet({ children }) {
  return (
    <li className="flex items-start gap-2 text-sm text-black/70">
      <span className="mt-0.5 grid h-5 w-5 place-items-center rounded-full bg-black text-white">
        <Check className="h-3.5 w-3.5" />
      </span>
      <span>{children}</span>
    </li>
  );
}

function PitchItem({ n, t, d }) {
  return (
    <div className="rounded-2xl border border-black/5 bg-white/60 p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-black/45">#{n}</div>
        <Badge className="text-[11px]">{t}</Badge>
      </div>
      <div className="mt-2 text-sm text-black/70">{d}</div>
    </div>
  );
}

function ResultTile({ label, value, hint, icon: Icon }) {
  return (
    <div className="rounded-3xl border border-black/5 bg-white/60 p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold text-black/45">{label}</div>
          <div className="mt-1 text-[15px] font-semibold">{value}</div>
        </div>
        <div className="grid h-10 w-10 place-items-center rounded-2xl bg-black text-white">
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <div className="mt-2 text-xs text-black/50">{hint}</div>
    </div>
  );
}

function InfoRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-black/5 bg-white/60 p-4">
      <div className="grid h-10 w-10 place-items-center rounded-2xl bg-black text-white">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <div className="text-xs font-semibold text-black/45">{label}</div>
        <div className="mt-1 text-sm font-medium">{value}</div>
      </div>
    </div>
  );
}
