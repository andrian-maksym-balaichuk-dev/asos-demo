# GraphQL — ťahák pre prezentujúceho (Demo 3)

Len pre teba, nie na plátno. Čas na tvoju časť: max. **1:45** pre demo, zvyšok podľa slidu 18.
Všetky čísla nižšie sú overené na bežiacom deme.

---

## 1. Pointa za 20 sekúnd

> GraphQL dovolí klientovi jednou query povedať presne, aké dáta chce.
> Jeden request z prehliadača však **neznamená jeden dotaz do databázy**.
> Ukážeme tú istú query: naivne **101** SQL dotazov, s DataLoaderom **2**. JSON je rovnaký.

---

## 2. Čo je GraphQL (vysvetli jednoducho)

- **Dotazovací jazyk pre API** (Facebook 2012, open-source 2015, dnes GraphQL Foundation).
- Server má **schému**, teda typy a polia, ktoré existujú. Klient pošle **query**, v ktorej vyberie polia, a dostane JSON **presne v tvare query**.
- Typicky **jeden endpoint**, `POST /graphql`, namiesto veľa URL ako pri REST.
- Za každým poľom je **resolver**, funkcia, ktorá dané pole naplní. Server prechádza query ako strom a volá resolvery.

**Pojmy:**

| Pojem | Význam | V našom deme |
|---|---|---|
| Schéma (SDL) | zoznam typov a polí | `Event`, `Seat`, `Price`, `Query` |
| Query | čítanie dát | `event(id: "42") { seats { id price { amount } } }` |
| Mutation | zápis dát | nemáme (rezervácie robí REST) |
| Subscription | push zmien (zvyčajne cez WebSocket) | nemáme (push robí Demo 4) |
| Resolver | funkcia, ktorá vráti hodnotu poľa | `Seat.price`, `Event.seats` |
| Introspekcia | schéma sa dá spýtať sama na seba | funguje (nástroje z nej robia autocomplete) |

**Naša schéma** (skutočná, z `GET /graphql/schema.graphql`):

```graphql
type Query  { event(id: ID!): Event! }
type Event  { id: ID!  name: String  venue: String  seats(limit: Int! = 10): [Seat!]! }
type Seat   { id: ID!  row: String!  number: Int!  price: Price }
type Price  { amount: Float!  currency: String!  internalCost: Float! }   # internalCost iba admin
```

---

## 3. GraphQL vs. REST: kedy čo

| | REST | GraphQL |
|---|---|---|
| Endpointy | veľa URL (`/events/42`, `/events/42/seats`) | jeden `/graphql` |
| Tvar odpovede | určuje server | určuje **klient** v query |
| Over-fetching (príde viac, než treba) | častý | nie, len vybrané polia |
| Under-fetching (treba ďalší request) | častý (N requestov z klienta) | jedna query |
| HTTP cache | jednoduchá (GET + URL) | ťažšia (väčšinou POST, rôzne query) |
| Chyby | HTTP status (404, 409…) | väčšinou HTTP 200 + pole `errors` |
| Verzovanie | `/v1`, `/v2` | pridávaš polia, staré označíš `@deprecated` |
| Riziko | — | drahé query, N+1, autorizácia **po poliach** |

**Kedy GraphQL:** frontend alebo mobil, ktorý potrebuje pre rôzne obrazovky rôzne dáta z viacerých zdrojov.
**Kedy nie:** jednoduché CRUD API, verejné API s dôrazom na HTTP cache, upload súborov, server-to-server volania (tam skôr REST alebo gRPC).

---

## 4. Ako sa vykoná naša query (krok po kroku)

```graphql
{ event(id: "42") { seats(limit: 100) { id price { amount currency } } } }
```

1. `Query.event(id: "42")` vráti len referenciu `Event(id=42)` → **0 SQL**.
2. `Event.seats(limit: 100)` → `SELECT … FROM seats … LIMIT 100` → **1 SQL**, 100 sedadiel.
3. `id` je hodnota v objekte → **0 SQL**.
4. `Seat.price` sa zavolá **pre každé zo 100 sedadiel**:
   - **naivne:** každé volanie urobí vlastný `SELECT … FROM prices WHERE seat_id = 'A1'` → **100 SQL**
   - **DataLoader:** volania len zapíšu kľúč (`'A1'`, `'A2'`…). Na konci kola event loopu sa pošle **jeden** `SELECT … WHERE seat_id IN ('A1', …, 'J10')` → **1 SQL**
5. Spolu: naivne **1 + 100 = 101**, batching **1 + 1 = 2**.

**Prečo vzniká N+1:** resolver pre `price` vidí len jedno sedadlo. Nevie, že existuje ďalších 99. Klient poslal 1 request, ale server ho rozložil na 101 malých otázok.

**Ako DataLoader pomôže:** nezmení schému ani odpoveď. Iba **zozbiera** všetky požiadavky z jedného kola a pošle ich **naraz**. Je **nový pre každý request**, aby sa cache jedného používateľa nedostala k inému.

---

## 5. Kde je to v kóde (čo otvoriť vo VS Code)

| Čo | Súbor : riadok |
|---|---|
| Typy schémy (`Price`, `Seat`, `Event`, `Query`) | [schema.py:62–124](../TicketFlow-demo/app/graphql/schema.py#L62-L124) |
| SQL dotazy (jeden vs. `IN (…)`) | [schema.py:32–54](../TicketFlow-demo/app/graphql/schema.py#L32-L54) |
| **Resolver `Seat.price` (celý rozdiel dema)** | [schema.py:84–88](../TicketFlow-demo/app/graphql/schema.py#L84-L88) |
| **Naivne vs. batching, dve funkcie vedľa seba** | [schema.py:131–140](../TicketFlow-demo/app/graphql/schema.py#L131-L140) |
| **DataLoader, dávková funkcia** `load_prices_in_one_query` | [schema.py:143–159](../TicketFlow-demo/app/graphql/schema.py#L143-L159) |
| Ochrana `limit` 1–100 | [schema.py:96–101](../TicketFlow-demo/app/graphql/schema.py#L96-L101) |
| Autorizácia poľa `internalCost` | [schema.py:68–73](../TicketFlow-demo/app/graphql/schema.py#L68-L73) |
| Hĺbka query max. 6 | [schema.py:124](../TicketFlow-demo/app/graphql/schema.py#L124) |
| Nový kontext + DataLoader na každý request | [schema.py:180–197](../TicketFlow-demo/app/graphql/schema.py#L180-L197) |
| Endpointy `/graphql` a `/graphql/naive` | [endpoint.py:30–69](../TicketFlow-demo/app/graphql/endpoint.py#L30-L69) |
| **Počítanie SQL (event hook)** | [db.py:37–65](../TicketFlow-demo/app/data/db.py#L37-L65) |
| Tabuľky `seats` a `prices` (oddelené zámerne) | [models.py:25–43](../TicketFlow-demo/app/data/models.py#L25-L43) |

**Ak ukazuješ kód, stačia tieto 2 výrezy (do 30 s):**

Resolver, celý rozdiel je v jednej podmienke ([schema.py:84](../TicketFlow-demo/app/graphql/schema.py#L84)):

```python
async def price(self, info) -> Price | None:
    # Tento resolver sa zavolá PRE KAŽDÉ sedadlo (100×). Celý rozdiel dema je tu:
    if info.context.mode == "naive":
        return await price_naive(info.context, self.event_id, self.id)
    return await price_batched(info.context, self.event_id, self.id)
```

Dve funkcie vedľa seba ([schema.py:131](../TicketFlow-demo/app/graphql/schema.py#L131)):

```python
async def price_naive(ctx, event_id, seat_id):
    """N+1: každé sedadlo si urobí VLASTNÝ SQL dotaz → 100 sedadiel = 100 dotazov."""
    rows = await ctx.fetch(SQL_PRICE_ONE_SEAT, {"event_id": event_id, "seat_id": seat_id})

async def price_batched(ctx, event_id, seat_id):
    """DataLoader: iba ZAPÍŠE kľúč. SQL sa spustí raz pre všetky zozbierané kľúče."""
    row = await ctx.price_loader.load((event_id, seat_id))
```

**Prečo veríme číslu 101/2:** [db.py:37](../TicketFlow-demo/app/data/db.py#L37) je SQLAlchemy hook `before_cursor_execute`. Zapíše **každý príkaz, ktorý naozaj odíde do PostgreSQL** na spojení daného requestu. Spojenie je v režime AUTOCOMMIT, takže sa nepočíta ani skrytý `BEGIN`. Číslo nikde nie je napísané ručne a odpoveď ho vracia v `extensions.sql.count`.

---

## 6. Demo v paneli (karta **C · GraphQL**)

| # | Klikni | Uvidíš | Povedz |
|---|---|---|---|
| 1 | **Naivný resolver** | **101** | „1 dotaz na sedadlá plus 1 dotaz na cenu za každé sedadlo.“ |
| 2 | **Batching (DataLoader)** | **2** | „Ceny naraz, jedným dotazom.“ |
| 3 | ukáž **JSON zhodný: ÁNO** | ÁNO | „Klient rozdiel nevidí. Databáza áno.“ |
| 4 | ukáž **SQL log** | vľavo `seat_id = 'A1'`, `'A2'`, … +98; vpravo `IN ('A1', 'A2', 'A3', … 100 hodnôt)` | „Toto je skutočný log z DB spojenia.“ |
| 5* | **limit: 500 → zamietnuté** | chyba, 0 SQL | „Server musí brániť drahé query.“ |
| 6* | **internalCost bez roly** | prístup zamietnutý | „Autorizácia je po poliach, nie po endpointe.“ |

\* len ak ostane čas alebo príde otázka.

**Záver:** „GraphQL znižuje počet requestov z klienta, nie automaticky počet dotazov do DB. Batching, autorizáciu a zložitosť query musí riešiť server.“

---

## 7. Ukážky naživo v termináli (bonus alebo pri otázkach)

Z priečinka `TicketFlow-demo`:

```bash
# porovnanie 101 vs 2 (fallback, ak panel nejde)
python3 scripts/demo_graphql.py --seats 100 --compare

# ľubovoľná query + skutočný počet SQL
python3 scripts/gql.py '{ event(id: "42") { seats(limit: 3) { id price { amount } } } }'
python3 scripts/gql.py --naive '{ event(id: "42") { seats(limit: 3) { id price { amount } } } }'
python3 scripts/gql.py --sql '{ event(id: "42") { name seats(limit: 3) { id price { amount } } } }'
python3 scripts/gql.py --admin '{ event(id: "42") { seats(limit: 1) { price { internalCost } } } }'

# celá schéma
curl -s localhost:8000/graphql/schema.graphql
```

**Overené počty** (ukazujú, že číslo zodpovedá query, nie je napísané ručne):

| Query | Naivne | Batching |
|---|---|---|
| `seats(limit: 100) { id price { amount currency } }` | **101** | **2** |
| `seats(limit: 10) { id price { amount } }` | 11 | 2 |
| `seats(limit: 3) { id price { amount } }` | 4 | 2 |
| `seats(limit: 5) { id }` (bez ceny) | 1 | 1 |
| `name seats(limit: 100) { id price { amount } }` | 102 | 3 (pribudne `SELECT … FROM events`) |

Pekný trik pri otázke „nie je to podvod?“: zmeň `limit` alebo pridaj `name` a číslo sa zmení presne podľa logiky.

---

## 8. Bezpečnosť a výkon GraphQL (ak príde otázka)

| Problém | Prečo vzniká | Riešenie | V našom deme |
|---|---|---|---|
| N+1 | resolver vidí len 1 objekt | DataLoader / batching | áno |
| Drahá query (`limit: 1000000`) | klient si query skladá sám | limity argumentov | `limit` max 100 |
| Hlboké vnorenie | `a { b { a { b … } } }` | limit hĺbky | `QueryDepthLimiter(6)` |
| Zložitosť | veľa polí × veľa riadkov | cost/complexity analýza, timeouty | len spomenúť |
| Autorizácia | jeden endpoint, veľa polí | kontrola **na úrovni poľa** | `internalCost` iba admin |
| Únik cache medzi ľuďmi | zdieľaný DataLoader | loader **na request** | áno |
| Neznáme query v produkcii | klient pošle čokoľvek | persisted queries (allowlist) | len spomenúť |
| Introspekcia v produkcii | útočník vidí celú schému | často sa vypína alebo obmedzuje | zapnutá (demo) |

---

## 9. Kde sa GraphQL používa v reáli

- **GitHub GraphQL API.** V dokumentácii GitHubu je Explorer, kde si query skúsiš v prehliadači.
- **Shopify** (Admin a Storefront API) pre e-shopy a mobilné aplikácie.
- **Facebook / Meta**, kde GraphQL vznikol pre mobilnú aplikáciu.
- Firmy s veľa frontendmi (web, iOS, Android) a mikroslužbami za nimi. GraphQL tam často slúži ako „brána“ (BFF / federation), ktorá skladá dáta z viacerých služieb.
- **Ako to vidieť sám:** otvor web, ktorý GraphQL používa, potom DevTools → Network → filter `graphql` a uvidíš `POST /graphql` s query v tele.

Príklady sú z pamäti, pred slidom si ich over v dokumentácii.

---

## 10. Otázky publika a krátke odpovede

**Je GraphQL rýchlejší než REST?**
Nie automaticky. Šetrí počet requestov z klienta, ale server môže robiť viac práce (N+1). Rýchlosť závisí od implementácie.

**Prečo nie stačí REST s parametrom `?fields=`?**
Pri jednoduchom API stačí. GraphQL sa oplatí pri zložitých vnorených dátach a mnohých klientoch s rôznymi potrebami.

**Dá sa GraphQL cacheovať?**
Áno, ale ťažšie. Väčšinou je to POST na jednu URL. Používa sa cache na klientovi (Apollo, Relay), persisted queries cez GET alebo cache v resolveroch.

**Prečo GraphQL vracia chybu s HTTP 200?**
Odpoveď môže byť čiastočne úspešná: niektoré polia majú dáta, iné chybu. Preto má pole `errors` vedľa `data`. Ukážka je `internalCost` bez roly.

**Čo je DataLoader, knižnica?**
Vzor aj knižnica (pôvodne z Facebooku, JavaScript). My používame `strawberry.dataloader` v Pythone. Princíp je rovnaký: zozbieraj kľúče, načítaj naraz, vráť v poradí.

**Prečo nový DataLoader na každý request?**
Cache v ňom patrí jednému používateľovi. Zdieľaný loader by mohol vrátiť dáta, na ktoré iný používateľ nemá právo.

**Nahrádza GraphQL REST?**
Nie. Často žijú vedľa seba: GraphQL pre frontend a REST alebo gRPC medzi službami.

**Prečo nemáte mutácie?**
V deme ide o čítanie a N+1. Zápisy (rezervácie) ukazuje REST v Deme 1.

---

## 11. Čo nehovoriť

- ✗ „GraphQL je vždy rýchlejší / lepší ako REST.“
- ✗ „GraphQL nejde cacheovať.“
- ✗ „101 dotazov je vždy zlé.“ Pri 3 sedadlách je to len 4 vs. 2. Problém rastie s počtom položiek.
- ✗ Nečítaj nahlas celý SQL log ani JSON. Ukáž 2–3 riadky.
- ✓ Ak by panel ukázal iné číslo ako 101/2, povedz to **skutočné** a vysvetli prečo (napr. „pridali sme pole `name`, preto +1“).

---

## 12. Prechody

- **Pred tebou (z Dema 2):** „Interné volania už fungujú. Frontend však stále potrebuje rôzne dáta pre rôzne obrazovky.“
- **Po tebe (do Dema 4):** „Dáta vieme načítať. Čo ak sa zmenia až po tom, ako pôvodný request skončil?“
