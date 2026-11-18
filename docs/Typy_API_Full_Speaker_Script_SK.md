# TYPY API — KOMPLETNÝ HOVORENÝ TEXT PREZENTÁCIE

**Téma:** Typy API: ako vybrať správnu komunikáciu v reálnom systéme  
**Publikum:** študenti 2. ročníka inžinierskeho štúdia informatiky  
**Jazyk:** slovenčina  
**Čas:** 40:00 — štyria prezentujúci po presne 10:00  
**Koncept:** jedna ilustračná architektúra TicketFlow (rezervácia miest a spracovanie platieb).  

> Toto je text na rozprávanie, nie text na slidy. Slidy zobrazujú len hlavnú myšlienku, technický tok alebo porovnanie. Časy zahŕňajú prípadné krátke ukážky a prepínanie slidov. Príklady a čísla označené „model“ nie sú benchmarkom.

## PREZENTUJÚCI 1 — REST, HTTP, OpenAPI (00:00–10:00)

### Slide 01 — Nie je jedno API pre všetko (1:20)
**Na slide:** „Typy API“; *Jeden systém. Viac spôsobov komunikácie.*; štyri malé štítky REST / RPC / GraphQL / Eventy.

**Hovorený text:**
V praxi sa málokedy rozhodujeme len medzi dvoma názvami technológií. Rozhodujeme sa najmä podľa toho, kto s kým komunikuje, či potrebujeme okamžitú odpoveď, aké dáta prenášame a čo sa má stať, keď sieť zlyhá. Predstavme si TicketFlow, službu na rezerváciu miest na koncert. Používateľ otvorí aplikáciu, vyberie sedadlo A7, odošle rezerváciu, následne zaplatí a očakáva potvrdenie. Znie to jednoducho, ale každá časť má odlišné požiadavky: frontend potrebuje verejné rozhranie, interná služba potrebuje rýchly typovaný kontrakt a platobná brána nám odošle výsledok neskôr. Ukážeme preto šesť často používaných spôsobov komunikácie: REST, SOAP, gRPC, GraphQL, WebSocket a webhooks. Pridáme aj OpenAPI, WSDL a Protocol Buffers, ale tie nie sú ďalšie rovnocenné druhy API. Sú to opisy kontraktov alebo formáty správ. Našou otázkou nebude „čo je najmodernejšie“, ale „čo je správne pre konkrétny problém“.

### Slide 02 — TicketFlow: jedna architektúra (1:40)
**Na slide:** Diagram: Klient → Public API → Rezervácie → Inventár; Platobná brána → Webhook → Rezervácie → WebSocket → Klient.

**Hovorený text:**
Pozrime sa na architektúru. Klient cez verejné API načíta ponuku a vytvorí rezerváciu. Rezervačná služba potrebuje preveriť, či je miesto ešte dostupné; na to komunikuje s interným inventárom. Po vytvorení objednávky iniciuje platbu. Výsledok však nemusí prísť počas pôvodného HTTP requestu: používateľ môže prejsť na externú platobnú stránku alebo sa platba spracuje asynchrónne. Platobný poskytovateľ preto informuje náš backend samostatnou udalosťou a backend potom aktualizuje pripojený prehliadač. To sú minimálne tri rozdielne komunikačné vzory: request-response, interné RPC a asynchrónna notifikácia. Jedna aplikácia môže používať viac technológií bez toho, aby to bol zlý návrh. Dôležité je, aby každá hranica mala jasný kontrakt, bezpečnosť, správne spracovanie zlyhaní a možnosť merania. V jednotlivých blokoch tejto prezentácie budeme pridávať k tomu istému systému vždy jednu časť a vysvetlíme, prečo vzniká.

### Slide 03 — REST: zdroje a HTTP sémantika (1:45)
**Na slide:** GET /events/42, POST /reservations, 201 Created, 409 Conflict; „zdroj ≠ operácia“.

**Hovorený text:**
REST je architektonický štýl, nie synonymum pre JSON ani pre každý endpoint dostupný cez HTTP. V praxi sa pri resource-oriented rozhraní sústredíme na zdroje — napríklad udalosti, sedadlá a rezervácie — ktoré identifikujeme pomocou URI. HTTP poskytuje operácie a ich význam: GET má zdroj čítať, POST zvyčajne vytvára nový výsledok alebo vykonáva spracovanie, PUT nahrádza reprezentáciu a DELETE žiada odstránenie zdroja. Status kódy hovoria, ako požiadavka dopadla. Pri vytvorení rezervácie môže byť výsledkom 201 Created; ak miesto už nie je k dispozícii, dáva zmysel 409 Conflict. Dôležitá je idempotencia: opakované PUT alebo DELETE by mali mať rovnaký zamýšľaný efekt ako jediné volanie. To neznamená, že server nemôže zapisovať logy. POST štandardne takúto vlastnosť negarantuje. HTTP cache, validácia a štandardné nástroje robia REST praktickým najmä pre verejné API. Zároveň však samotná voľba REST nevyrieši súbeh ani chyby v doménovej logike.

### Slide 04 — Retry nie je to isté ako konkurencia (1:55)
**Na slide:** Dve samostatné vetvy: rovnaký klient + retry → ten istý výsledok; dvaja klienti → databázové obmedzenie → 1 úspech, 1 konflikt.

**Hovorený text:**
Tu sú dva problémy, ktoré sa často zamieňajú. Najprv klient odošle POST na vytvorenie rezervácie. Server rezerváciu vytvorí, ale odpoveď sa stratí. Klient nevie, či má request zopakovať. Ak by opakovanie vytvorilo ďalší záznam, zákazník môže dostať dve objednávky. Riešením je napríklad idempotency key: server si zapamätá identitu logickej požiadavky a pri rovnakom opakovaní vráti už vytvorený výsledok. Teraz druhý problém: klient A a klient B si súčasne vyberú miesto A7. Každý má iný idempotency key. V takom prípade samotné kľúče nepomôžu. Pravidlo „jedno miesto môže mať len jednu aktívnu rezerváciu“ musí presadiť konzistentná operácia v úložisku — napríklad transakcia s unikátnym obmedzením alebo podmienený atómový update. Len jeden môže uspieť, druhý dostane konflikt. Najdôležitejšia lekcia: spracovanie retry a ochrana pred race condition sú dva oddelené návrhové problémy.

### Slide 05 — OpenAPI nie je nový protokol (1:25)
**Na slide:** Kontrakt OpenAPI → Swagger UI / SDK / Testy; malý príklad endpointu bez zdrojového kódu.

**Hovorený text:**
Keď rozhranie používa viac tímov, samotná wiki stránka s príkladmi nestačí. Potrebujeme kontrakt, ktorému rozumejú ľudia aj nástroje. OpenAPI umožňuje opísať HTTP endpointy, parametre, schémy requestov a odpovedí aj bezpečnostné požiadavky. Z toho sa dá vytvoriť prehľadná dokumentácia pomocou Swagger UI, klientské SDK alebo kontraktové testy. Swagger teda nie je konkurent RESTu; je to ekosystém nástrojov okolo rozhraní opisovaných pomocou OpenAPI. Z pohľadu dlhodobej údržby je kritická kompatibilita. Ak zmeníme názov JSON poľa alebo odstránime hodnotu enumu, staršia mobilná aplikácia môže prestať fungovať, hoci backend už beží v novej verzii. Preto je dokumentovaný kontrakt aj spôsob koordinácie zmien medzi tímami. Dokumentácia však sama nevynúti správny runtime — správanie musíme testovať.

### Slide 06 — DEMO: dve rezervácie, jedno miesto (1:55)
**Na slide:** Stav A7: voľné → rezervované; retry vráti rovnaké ID; súbeh skončí 201 / 409. Krátka tabuľka „výhody / hranice RESTu“.

**Hovorený text:**
Teraz si to overíme v pripravenom demo paneli. Najprv vytvoríme rezerváciu miesta A7 a zobrazíme identifikátor. Klikneme na zopakovanie rovnakej požiadavky s rovnakým kľúčom: identifikátor zostane identický a nevznikne druhá rezervácia. Potom scenár resetujeme a odošleme dve odlišné rezervácie súčasne. Vidíme jeden úspešný výsledok a jeden konflikt; databáza obsahuje len jedného vlastníka miesta. Toto nie je benchmark rýchlosti, ale dôkaz zachovania invariantu. REST tu ponúka jednoduchý verejný kontrakt, HTTP ekosystém a ľahké debugovanie. Nevýhodou môže byť množstvo špecializovaných endpointov pri komplikovaných obrazovkách a potreba navrhnúť správnu kompatibilitu, validáciu, chyby a autorizáciu. Ak má aplikácia jednoduchý resource-oriented model, REST by som bral ako rozumný východiskový bod. Pri interných službách alebo komplexnom výbere dát už však môžu dávať väčší zmysel ďalšie riešenia. Odovzdávam slovo časti o RPC.

## PREZENTUJÚCI 2 — SOAP, WSDL, gRPC, PROTOBUF (10:00–20:00)

### Slide 07 — Public API a interná komunikácia (1:20)
**Na slide:** Frontend ↔ public HTTP; backend ↔ typované interné RPC; partner ↔ staršie B2B.

**Hovorený text:**
V prvej časti sme videli verejné API, ktoré obsluhuje web a mobil. Vnútri systému však máme inú situáciu. Rezervačná služba musí volať inventár, ceny alebo kapacitné pravidlá, často veľakrát počas jednej používateľskej operácie. Volajú sa navzájom služby, ktorých implementácie sú pod kontrolou jedného tímu či firmy. Tu je dôležitý strojovo definovaný kontrakt, propagácia timeoutu a jednoduché generovanie klienta. Zároveň môže byť potrebné komunikovať so starším CRM partnera, ktoré už roky poskytuje SOAP rozhranie. Nemá zmysel presadzovať jeden protokol na všetky integračné hranice. Rozlišujme najmä model komunikácie, formát správ, spôsob definovania kontraktu a prevádzkové požiadavky. SOAP a gRPC budeme preto porovnávať ako rôzne spôsoby vzdialeného volania, nie ako karikatúru „starý zlý XML svet proti novému rýchlemu svetu“.

### Slide 08 — SOAP: správa a WSDL kontrakt (1:40)
**Na slide:** SOAP Envelope {Header, Body}; WSDL → operácie, typy, endpoint.

**Hovorený text:**
SOAP je protokol výmeny štruktúrovaných správ, typicky reprezentovaných XML. Základ správy tvorí Envelope, voliteľný Header a Body, v ktorom je samotná operácia alebo výsledok. Pri chybe sa používa SOAP Fault. Veľkou výhodou v podnikovom prostredí je formálny kontrakt: WSDL opisuje, aké operácie služba ponúka, aké dátové typy očakáva a ako je dostupná. Z kontraktu môžu nástroje generovať klientov aj na strane partnerských systémov. SOAP ekosystém zahŕňa tiež možnosti rozšírenej bezpečnosti, napríklad WS-Security, ak sú na oboch stranách podporované. Nevýhodou je zložitejšie XML a integračný stack, s ktorým sa novému tímu môže pracovať ťažšie. Ak však partner vyžaduje existujúcu WSDL a integrácia je stabilná, migrácia len preto, že máme novšiu technológiu, nemusí mať obchodný ani technický zmysel.

### Slide 09 — gRPC: kontrakt pred implementáciou (1:45)
**Na slide:** .proto → generated stubs → HTTP/2 RPC → Protobuf binary.

**Hovorený text:**
Pri gRPC začíname opisom služby a jej dátových typov v súbore .proto. Generátor z neho pripraví typované klientské a serverové rozhrania pre viacero jazykov. Klient potom volá vzdialenú metódu spôsobom, ktorý pripomína lokálne volanie funkcie, ale v skutočnosti ide o komunikáciu po sieti. Bežné gRPC používa HTTP/2 a často Protocol Buffers ako kompaktnú binárnu serializáciu. Protobuf ukladá identifikátory polí, takže správa nepotrebuje opakovať dlhé textové názvy všetkých vlastností. Výhoda je jednoznačný typovaný kontrakt a dobrá podpora mikroservisov. Nie je však korektné povedať, že gRPC je v každom systéme automaticky rýchlejšie než REST. Záleží na veľkosti správ, serializácii, sieťovej latencii, implementácii a infraštruktúre. Pri zmene schémy musíme navyše rešpektovať pravidlá evolúcie polí, napríklad nerecyklovať čísla odstránených položiek.

### Slide 10 — Štyri komunikačné modely gRPC (1:40)
**Na slide:** Unary; server streaming; client streaming; bidirectional streaming — štyri minidiagramy.

**Hovorený text:**
gRPC nie je zaujímavé len preto, že má binárne správy. Podporuje štyri modely komunikácie. Unary RPC je najbližšie bežnému request-response: jeden request a jedna odpoveď. Server streaming po jednom requeste postupne posiela viac výsledkov, napríklad počas dlhšieho spracovania. Client streaming umožňuje klientovi poslať sériu údajov a dostať na konci jednu odpoveď, napríklad pri agregácii meraní. Bidirectional streaming umožňuje obom stranám posielať správy priebežne. Pre jednoduché overenie, či je sedadlo voľné, je unary úplne postačujúce. Stream je vhodný len ak má zmysel postupne doručovať nové dáta. Pri každom streamingu stále treba riešiť zlyhanie spojenia, rušenie a reguláciu toku dát. Výber zložitejšieho režimu len preto, že ho framework podporuje, zbytočne zvyšuje prevádzkové riziká.

### Slide 11 — Deadline: sieťové volanie nie je funkcia (1:40)
**Na slide:** Gateway budget 500 ms → Inventory delay 900 ms → DEADLINE_EXCEEDED; cancellation/retry.

**Hovorený text:**
Dôležitý rozdiel medzi lokálnou funkciou a RPC je neistota. Vzdialený server môže spracovanie dokončiť, ale odpoveď sa stratí alebo príde neskoro. Ak request prechádza troma službami a každá čaká neobmedzene, systém dokáže pri malom výpadku vyčerpať spojenia a vlákna. Preto sa pri gRPC používajú deadlines: klient dáva časový rozpočet, dokedy potrebuje výsledok. Ak inventár odpovie až po uplynutí rozpočtu, klient dostane napríklad stav DEADLINE_EXCEEDED. Zrušenie na strane klienta však automaticky neznamená, že server stihol zastaviť všetku svoju prácu. Pri zlyhaní možno pridať retry, ale len s limitmi, backoffom a správnou idempotenciou. Inak môže opakovanie volaní preťažený server ešte viac zahltiť. Dobrá architektúra preto pracuje s timeoutmi, observabilitou a jasnými zodpovednosťami, nielen s typmi správ.

### Slide 12 — DEMO: SOAP kontrakt a gRPC deadline (1:55)
**Na slide:** SOAP cez WSDL / gRPC cez .proto; healthy reply / deadline exceeded; plusy a mínusy.

**Hovorený text:**
V krátkej ukážke uvidíme obe riešenia na tom istom probléme: zistiť dostupnosť sedadla. Naľavo otvoríme WSDL a ukážeme operáciu poskytovanú starším partnerom. Ide o existujúci kontrakt, nie o prezentáciu HTML. Napravo vidíme gRPC službu a vygenerované typy. Najprv zavoláme inventár normálne a dostaneme typovanú odpoveď. Potom umelo pridáme oneskorenie servera a nastavíme kratší deadline; výsledkom je očakávané prekročenie časového limitu. Nezobrazujeme vymyslené tvrdenia o násobnom zrýchlení — demonštrujeme kontrakt a zlyhanie. SOAP je vhodný na integráciu so zavedenými podnikovými službami, ale prináša náročnejší XML ekosystém. gRPC sa hodí na interné RPC s generovanými klientmi, no vyžaduje prevádzkovú podporu a vhodné gateway riešenie pre niektorých browserových klientov. V nasledujúcej časti sa pozrieme na úplne iný problém: ako frontend získa správny tvar dát.

## PREZENTUJÚCI 3 — GRAPHQL (20:00–30:00)

### Slide 13 — Každý klient potrebuje iné dáta (1:20)
**Na slide:** Mobil: 3 polia; Web: 8 polí; Admin: ďalšie prehľady.

**Hovorený text:**
Predstavme si detail koncertu v troch aplikáciách. Mobil zobrazuje názov, cenu a dostupnosť; desktop pridáva mapu sedadiel; administrácia potrebuje štatistiky, rezervácie a stav platieb. Ak každá obrazovka používa presne ten istý široký REST endpoint, môže sťahovať veľa nepotrebných údajov. Ak zas máme príliš drobné endpointy, klient skladá stránku z viacerých požiadaviek. Tieto problémy sa často nazývajú over-fetching a under-fetching. REST ich vie riešiť agregovanými endpointmi alebo voliteľnými parametrami. GraphQL volí iný kompromis: server poskytne typovanú schému a klient v jej rámci vyberie presne tie polia a vzťahy, ktoré potrebuje. Je to výhodné najmä pri viacerých frontendoch a rýchlo sa meniacich požiadavkách na obrazovky. Flexibilita pre klienta ale znamená väčšiu zodpovednosť backendu, ako uvidíme na ďalších slidoch.

### Slide 14 — GraphQL: schéma a resolvery (1:45)
**Na slide:** Query → validation → resolver tree → JSON podľa výberu polí; typy Query/Mutation/Subscription.

**Hovorený text:**
GraphQL je jazyk na dotazovanie API a vykonávací model, nie databáza. Server definuje schému — typy, polia, argumenty a vzťahy. Klient pošle query, server ju validuje voči schéme a následne vyhodnocuje jednotlivé polia pomocou resolverov. Resolver môže prečítať databázu, cache alebo zavolať ďalšiu službu. Výsledný JSON zodpovedá štruktúre vybraných polí, takže klient pozná svoj dátový kontrakt už pri písaní query. Query sa bežne používa na čítanie a Mutation na operácie meniace stav; subscriptions podporujú distribúciu aktualizácií, podľa konkrétnej implementácie a transportu. Najdôležitejšie je uvedomiť si, že jeden GraphQL request nie je automaticky jedna databázová operácia. Logika resolverov dokáže vytvoriť veľa ďalších dotazov, a to aj keď klient urobil len jeden HTTP request. Preto potrebujeme sledovať vykonávanie pod povrchom.

### Slide 15 — N+1: jeden request, 101 dotazov (1:45)
**Na slide:** 100 sedadiel + ceny → 1 + 100 SQL vs batching → 1 + 1 SQL. „Ilustračný model“.

**Hovorený text:**
Uvažujme model, v ktorom načítame sto sedadiel jedným SQL dotazom a pre každé potrebujeme z inej tabuľky zistiť cenu. Naivný GraphQL resolver načíta cenu zvlášť pre každé sedadlo. Výsledkom môže byť 1 plus 100, teda 101 SQL volaní. To je známy N+1 problém. Riešením býva DataLoader alebo podobný mechanizmus, ktorý v rámci jedného requestu zhromaždí identifikátory sedadiel a pošle hromadný dotaz. V našom ilustračnom modeli sa počet SQL volaní zníži na dva. Pozor, tým netvrdíme, že aplikácia je päťdesiatkrát rýchlejšia. Skutočná latencia závisí aj od indexov, veľkosti výsledkov, siete a databázového plánovača. Význam ukážky je iný: GraphQL nám dáva pohodlný klientsky model, ale nevhodná implementácia resolverov môže presunúť vysoké náklady dovnútra servera.

### Slide 16 — Flexibilita má cenu (1:50)
**Na slide:** Široká query → veľa vetiev; hĺbka, šírka, complexity budget, autorizácia.

**Hovorený text:**
Druhým problémom je to, že klient si vie vyžiadať veľký alebo veľmi vnorený graf dát. Obmedziť len hĺbku nestačí: aj dotaz s relatívne malou hĺbkou môže mať veľa aliasov alebo veľmi široké zoznamy. Ak každý objekt vyvolá drahé externé RPC, problém sa rýchlo násobí. Preto produkčný GraphQL server potrebuje stránkovanie, odhad ceny dotazu, limity, timeouty a sledovanie pomalých resolverov. Treba tiež správne vynucovať autorizáciu na úrovni objektov a polí. To, že má schéma typ `Customer`, neznamená, že každý autentifikovaný používateľ môže vidieť ľubovoľného zákazníka. Z pohľadu prevádzky sú dôležité aj metriky: koľko backendových volaní vzniklo, aká je p95 latencia a kde request strávil čas. Technológia nie je zlá; len prenáša časť zložitosti z frontendov do backendovej vrstvy.

### Slide 17 — REST alebo GraphQL? (1:35)
**Na slide:** Decision card: stabilné zdroje / rôznorodé obrazovky / caching / komplexita.

**Hovorený text:**
Pre stabilný katalóg s dobre definovanými zdrojmi a malým počtom klientov môže REST ponúknuť jednoduchší vývoj, bežné HTTP cachovanie a zrozumiteľné logovanie. GraphQL je silnejší, keď viaceré klientské aplikácie často potrebujú odlišné kombinácie údajov a vyvíjajú sa nezávisle. Platíme však za to väčšou zložitosťou pri cache, riadení náročnosti dotazov a observabilite resolverov. Nie je správne tvrdiť, že GraphQL automaticky šetrí sieť v každom prípade: výsledok závisí od požadovaných dát a implementácie. Rovnako nie je pravda, že REST je nevyhnutne chatty; môžeme vytvoriť endpoint optimalizovaný pre obrazovku. Pri výbere by som meral p95 čas odozvy, počet interných dotazov, veľkosť prenesených dát a celkové náklady na údržbu. V praxi môže byť správna aj kombinácia oboch prístupov.

### Slide 18 — DEMO: naivný resolver verzus batching (1:45)
**Na slide:** Rovnaký výsledok dát; SQL counter „101 → 2“; sekundárne p95 označené len ak merané.

**Hovorený text:**
V demo paneli otvoríme rovnaký GraphQL dotaz na sto sedadiel s cenami. Najprv zapneme naivný režim. Server spracuje query správne, ale počítadlo skutočných SQL dotazov ukáže sto jeden. Potom prepneme na batching: pre rovnaké dáta uvidíme dva SQL dotazy. Tieto čísla vzniknú z našej pripravenéj implementácie, nie z ručne napísaného obrázka. Výsledok pre klienta sa nezmení, ale práca backendu áno. Je to veľmi dobrý príklad toho, prečo pri porovnávaní API technológií nestačí pozerať na počet HTTP volaní. Ak by sme išli do produkcie, otestovali by sme aj latenciu, CPU, súbeh a reálne dátové objemy. Po tomto demu prejdeme k poslednému komunikačnému problému: čo robiť, keď zmena stavu nastane až po skončení pôvodného HTTP requestu.

## PREZENTUJÚCI 4 — WEBSOCKET, SSE, WEBHOOKS (30:00–40:00)

### Slide 19 — Platba nepríde v tej istej odpovedi (1:25)
**Na slide:** POST /payments → 202/PENDING; neskôr payment.succeeded.

**Hovorený text:**
Keď používateľ spustí platbu, výsledok nemusí byť okamžite známy. Backend môže odpovedať, že požiadavku prijal a stav je PENDING. O chvíľu, niekedy až po návrate z platobnej brány, sa objednávka potvrdí. Pôvodné HTTP spojenie už skončilo a prehliadač nečaká na ďalšiu odpoveď. Máme preto dve samostatné otázky. Ako náš server zistí, že externá platba uspela? A ako potom oznámi zmenu používateľovi? Na prvú otázku často odpovedajú webhooks, čiže HTTP udalosti medzi servermi. Na druhú polling, Server-Sent Events alebo WebSocket. Tieto technológie sa dopĺňajú, nie sú to priamy konkurenti. Dôveryhodný výsledok platby sa musí uložiť na serveri; notifikácia v prehliadači slúži len na aktuálne zobrazenie stavu. Takéto oddelenie je zásadné pre spoľahlivosť.

### Slide 20 — Polling, SSE a WebSocket (1:35)
**Na slide:** tri čisté sekvencie; model „1 000 klientov / každých 5 s = 12 000 requestov/min“.

**Hovorený text:**
Najjednoduchšia možnosť je polling: klient sa každých pár sekúnd opýta servera, či sa stav zmenil. Je to robustné a ľahko sa nasadzuje, ale veľká časť požiadaviek môže byť zbytočná. Ak máme tisíc klientov a každý sa pýta raz za päť sekúnd, vznikne dvanásťtisíc requestov za minútu. Je to len modelový výpočet, nie meranie konkrétneho systému. SSE udržiava HTTP spojenie, cez ktoré server posiela udalosti jedným smerom k klientovi. Je vhodné napríklad na oznamovanie priebehu alebo notifikácií. WebSocket umožňuje dlhodobé obojsmerné posielanie správ, napríklad pri spoločnom editovaní alebo interaktívnom chate. Má však vlastné náklady: otvorené spojenia, load balancing, autentifikácia, heartbeat a reconnect. Preto by som pri jednoduchých jednosmerných stavových aktualizáciách najprv zvážil SSE, nie automaticky WebSocket.

### Slide 21 — WebSocket: spojenie nie je história (1:35)
**Na slide:** CONNECTED → DISCONNECTED → RECONNECT → HTTP snapshot → live updates.

**Hovorený text:**
WebSocket pripojenie môže kedykoľvek vypadnúť, napríklad pri prepnutí Wi-Fi na mobilné dáta. Po opätovnom pripojení klient nemá záruku, že automaticky dostane všetky udalosti, ktoré prišli počas výpadku. Preto sa nesmieme spoliehať iba na text „platba úspešná“, ktorý prišiel cez socket. Aplikácia potrebuje mať v databáze autoritatívny stav a po reconnecte si vyžiadať aktuálny snapshot, prípadne používať event ID a mechanizmus replay, ak ho server podporuje. Pri veľkom počte klientov treba riešiť aj pomalých odberateľov: ak nestíhajú čítať, fronty správ sa zväčšujú. Praktické riešenia sú obmedzenie bufferov, agregovanie aktualizácií a v krajnom prípade odpojenie pomalého klienta. Obidve strany spojenia potrebujú dôslednú autentifikáciu a obnovu oprávnení. Reálny čas bez mechanizmu obnovy stavu nie je spoľahlivý používateľský zážitok.

### Slide 22 — Webhook: over, deduplikuj, až potom spracuj (1:50)
**Na slide:** podpis → event ID → transakcia → ACK; varovanie „duplicitné a mimo poradia“.

**Hovorený text:**
Webhook je HTTP požiadavka, ktorú nám odošle cudzí systém po udalosti. Keď príde správa `payment.succeeded`, nesmieme jej veriť len preto, že obsahuje správny JSON. Najprv overujeme podpis, spravidla HMAC nad pôvodným telom požiadavky a často aj časové okno, aby sa obmedzilo prehratie starej správy. Potom spracujeme identifikátor udalosti. Poskytovateľ môže webhook poslať opakovane, napríklad keď nedostal našu odpoveď včas, preto musíme byť idempotentní a uložiť už spracované event ID. Zároveň nemožno všeobecne garantovať poradie doručenia udalostí. Stav objednávky sa preto má aktualizovať podľa platných pravidiel stavového automatu a ideálne transakčne. Potom rýchlo potvrdíme príjem a ďalšie náročné úlohy môžeme spracovať na pozadí cez internú frontu. Webhook nie je presne-jednorazové doručovanie; spoľahlivosť musí doplniť náš handler.

### Slide 23 — DEMO: webhook → databáza → WebSocket (2:00)
**Na slide:** štyri kroky, jeden zdroj pravdy; valid, duplicate, invalid signature, reconnect.

**Hovorený text:**
V poslednom deme máme otvorené dve okná prehliadača s rovnakou rezerváciou. Stav je PENDING. Simulovaný poskytovateľ pošle korektne podpísaný webhook. Backend overí podpis, zistí, že event ešte nespracoval, transakčne zmení stav objednávky a odošle aktualizáciu cez WebSocket obom pripojeným klientom. Teraz pošleme tú istú udalosť ešte raz: stav sa nezmení druhýkrát a systém označí udalosť ako duplicate. Nakoniec upravíme podpis; tento request musí byť odmietnutý a nesmie sa dostať k obchodnej logike. Ak jedno okno počas udalosti odpojíme a znovu pripojíme, jeho stav sa zosynchronizuje zo servera. Tým ukážeme celý návrh: webhook rieši server-to-server doručenie, databáza drží pravdu a WebSocket rieši používateľský zážitok v reálnom čase. Samotná animácia v prehliadači nie je dôkazom správnosti — potvrdenie musí existovať v úložisku.

### Slide 24 — Ako by sme API vybrali dnes? (1:35)
**Na slide:** rozhodovacia matica 6 technológií a otázky „kto / dáta / smer / zlyhanie?“.

**Hovorený text:**
Záverom si spojme jednotlivé technológie do jedného rozhodnutia. Pri bežnom verejnom resource-oriented API je REST často najjednoduchšia voľba, ktorú vieme opísať cez OpenAPI. SOAP sa uplatní tam, kde partneri používajú zavedené XML a WSDL kontrakty. gRPC dáva veľký zmysel pre typované interné RPC, najmä ak potrebujeme streaming a dobre definované deadlines. GraphQL je užitočné pre klientov s rôznorodými a meniacimi sa dátovými potrebami, ale musíme si strážiť resolvery, komplexitu a autorizáciu. WebSocket a SSE pomáhajú aktualizovať klienta, zatiaľ čo webhook oznamuje udalosť medzi servermi. Pri výbere si vždy položme štyri otázky: kto s kým komunikuje, aký je kontrakt dát, aký smer a životnosť spojenia potrebujeme a čo sa stane pri zlyhaní. Dobrý návrh API nepoznáme podľa názvu knižnice, ale podľa toho, ako sa systém správa aj keď veci nefungujú ideálne.

---

## Časový rozpis a odovzdanie slova

| Osoba | Slidy | Čas v bloku | Spolu |
|---|---|---|---|
| 1 | 01–06 | 1:20, 1:40, 1:45, 1:55, 1:25, 1:55 | 10:00 |
| 2 | 07–12 | 1:20, 1:40, 1:45, 1:40, 1:40, 1:55 | 10:00 |
| 3 | 13–18 | 1:20, 1:45, 1:45, 1:50, 1:35, 1:45 | 10:00 |
| 4 | 19–24 | 1:25, 1:35, 1:35, 1:50, 2:00, 1:35 | 10:00 |

*Pri demo slidoch je hovorený text kratší: čas zahŕňa živé ovládanie pripraveného dema a vysvetlenie výstupov. Pri prechodoch medzi hovoriacimi si vopred dohodnite jednu vetu na odovzdanie slova.*

## Primárne zdroje

- HTTP semantics RFC 9110 — https://www.rfc-editor.org/rfc/rfc9110.html
- OpenAPI — https://spec.openapis.org/oas/latest.html
- Swagger UI — https://swagger.io/tools/swagger-ui/
- SOAP 1.2 — https://www.w3.org/TR/soap12/
- WSDL — https://www.w3.org/TR/wsdl/
- gRPC core concepts — https://grpc.io/docs/what-is-grpc/core-concepts/
- gRPC deadlines — https://grpc.io/docs/guides/deadlines/
- Protocol Buffers — https://protobuf.dev/programming-guides/encoding/
- GraphQL performance — https://graphql.org/learn/performance/
- GraphQL security — https://graphql.org/learn/security/
- MDN WebSocket — https://developer.mozilla.org/en-US/docs/Web/API/WebSocket
- MDN Server-Sent Events — https://developer.mozilla.org/en-US/docs/Web/API/EventSource
- OWASP webhook security — https://cheatsheetseries.owasp.org/cheatsheets/Webhook_Security_Cheat_Sheet.html
- Stripe webhooks — https://docs.stripe.com/webhooks
