# Demo: real answers, fictional people

Every answer below is copied unchanged from the final evaluation run ([`eval/runs/final/results.json`](../../eval/runs/final/results.json)). Nothing was edited or picked for looks beyond choosing one case per category. The full records, with retrieved sources, timings and the judge's reasoning, are in [`answers.json`](answers.json).

**Data.** The Labour Law (*Zakon o radu*) is the official public text, in Cyrillic. The two job contracts and the annex in [`samples/`](../../samples/) are fictional: the people, companies (*Primer Softver d.o.o.*, *Primer Logistika d.o.o.*) and PIB numbers (100000001, 100000002) do not exist. The annex contains two planted defects on purpose.

Answer model `gemini-3.5-flash-lite`, temperature 0, top 5 passages, semantic search.

| Case | What it shows | Question | Answer |
|---|---|---|---|
| law-01 | Fact from the law | Koliko najmanje traje godišnji odmor? | Godišnji odmor traje najmanje 20 radnih dana [1]. |
| cyr-01 | Cyrillic question, Cyrillic answer | Колико по правилу траје радна недеља? | Радна недеља, по правилу, траје пет радних дана [1]. |
| cmp-01 | Comparing two contracts | Ko ima duži probni rad, Ana Jović ili Nikola Ilić? | Za ugovor o radu Ane Jović probni rad traje tri meseca [4]. Za ugovor o radu Nikole Ilića probni rad traje šest meseci [3]. Nikola Ilić ima duži probni rad [3][4]. |
| cf-03 | Annex overrides the contract | Koliko dana godišnjeg odmora ima Ana Jović? | U ugovoru o radu piše da zaposlena ima pravo na godišnji odmor u trajanju od 22 radna dana u kalendarskoj godini [1]. Međutim, aneks ugovora menja ugovor koji aneksira, pa važi vrednost iz aneksa prema kojoj zaposlena ima pravo na godišnji odmor u trajanju od 18 radnih dana u kalendarskoj godini [2]. |
| cf-04 | Contract checked against the law | Da li je godišnji odmor od 18 radnih dana iz aneksa ugovora Ane Jović u skladu sa Zakonom o radu? | Godišnji odmor od 18 radnih dana iz aneksa ugovora Ane Jović nije u skladu sa Zakonom o radu, jer zakon propisuje da zaposleni ima pravo na godišnji odmor u trajanju od najmanje 20 radnih dana [1][2]. |
| fp-04 | Corrects a false premise | Pošto zakon dozvoljava probni rad od godinu dana, da li poslodavac može da ugovori probni rad od 10 meseci? | Zakon ne dozvoljava probni rad od godinu dana, već je propisano da probni rad može da traje najduže šest meseci [1]. Pošto je najduže trajanje probnog rada šest meseci, poslodavac ne može da ugovori probni rad od 10 meseci [1]. |
| oos-07 | Says what is missing instead of guessing | Kolika je neto zarada Nikole Ilića? | U dostavljenim dokumentima se navodi samo bruto zarada Nikole Ilića koja iznosi 145.000,00 dinara, dok podatak o neto zaradi nije naveden [2]. |
| oos-01 | Refuses outside the documents | Koja je kazna za prebrzu vožnju? | Ne mogao sam da pronađem odgovor u dokumentima [1][2][3][4][5]. |

`amb-05` in `answers.json` shows a vague question ("Kolika je zarada?") over all documents, answered per document and per person.

## Run it yourself

```bash
cp .env.example .env              # add a Gemini (free) or OpenAI key
docker compose up -d --build
# put the official Zakon o radu PDF at data/zakon_o_radu.pdf, then:
./examples/demo/run_demo.sh       # uploads the documents and asks the questions above (needs curl + jq)
```

Answers can differ slightly between runs: free-tier lite models are not fully deterministic, even at temperature 0.

---

**Ukratko (SR):** svi odgovori iznad su prepisani bez izmena iz poslednjeg eval runa. Zakon o radu je zvaničan javni tekst; ugovori, osobe, firme i PIB-ovi su izmišljeni. `run_demo.sh` ponavlja demo na vašoj instalaciji.
