"""Election information feed for the fictional Republic of Veloria.

Outlets, parties, people and places are fictional; each item is modelled on a documented
real-world case (`analog`). Sources include a pro-incumbent state broadcaster, partisan outlets,
party pages, an anonymous "news" page, forwarded messages, a foreign state outlet, a
fact-checking coalition, the electoral commission and observers. Rounds 0-11 run from the
campaign through election day, counting, the declaration and the court challenge.

Fields
  round   0-11
  source  key into SOURCES (the outlet label agents see)
  text    what the agent reads
  note    hidden ground truth, never shown to agents
  status  hidden ground truth: accurate | slanted | misleading | false | unverified | partisan-claim
  major   True = shown to every agent regardless of media diet
  analog  the real-world case the item is modelled on
"""

SOURCES = {
    "VBC":      "VBC (state broadcaster)",
    "LEDGER":   "The Veloria Ledger (private daily newspaper)",
    "KITO":     "Kito TV (private TV station)",
    "VERI":     "VeriCheck Veloria (fact-checking coalition)",
    "UNITY":    "Unity Party official page",
    "CIVIC":    "Civic Front official page",
    "PATRIOTS": "Veloria Patriots Daily (news page)",
    "FWD":      "Message forwarded many times (WhatsApp group)",
    "TRENDS":   "Trending on Chirp",
    "FOREIGN":  "Valdoria Today (international news channel)",
    "IECV":     "Independent Electoral Commission of Veloria (official)",
    "COMMS":    "Communications Authority of Veloria (official)",
    "OBSERVER": "Regional election observer mission",
}

DIETS = {
    "@lena_codes":       ["LEDGER", "KITO", "VERI", "TRENDS"],
    "@farmer_jok":       ["VBC", "FWD", "CIVIC"],
    "@nightshift_nurse": ["FWD", "KITO", "TRENDS"],
    "@prof_halvard":     ["LEDGER", "KITO", "VERI", "OBSERVER"],
    "@mama_biz":         ["VBC", "UNITY", "FWD"],
    "@civic_watch_vel":  ["IECV", "VERI", "OBSERVER", "KITO", "PATRIOTS"],
    "@studentrights_k":  ["TRENDS", "PATRIOTS", "KITO"],
    "@taxi_rudo":        ["VBC", "FWD", "FOREIGN"],
}

DAY = ["Day 1 (12 days to the vote)", "Day 2 (11 days to the vote)", "Day 3 (10 days to the vote)",
       "Day 4 (9 days to the vote)", "Day 5 (8 days to the vote)", "Day 6 (7 days to the vote)",
       "Day 7 (campaign silence begins)", "Day 8 (ELECTION DAY)", "Day 9 (counting)",
       "Day 10 (counting)", "Day 11 (results declared)", "Day 12 (after the declaration)"]

FEED = [
    dict(round=0, source="VBC", major=True, status="slanted",
         text="President Ostrand opens the Kessa–North highway: 'a new era of prosperity for every Velorian family'. In brief: the opposition also held events today.",
         note="Bulletin gives 9 minutes to the ceremony and 40 seconds to the opposition.",
         analog="Zimbabwe 2023: EU observers found the state broadcaster gave over two-thirds of news coverage to the ruling party."),
    dict(round=0, source="LEDGER", major=False, status="misleading",
         text="'Sea of orange': Arden draws 50,000 in the Northern Province, organisers say.",
         note="Police estimated 15,000.",
         analog="Generic crowd-size inflation by partisan outlets; common in Kenya, Nigeria and elsewhere."),
    dict(round=0, source="KITO", major=True, status="accurate",
         text="First debate: Ostrand defends her inflation record; Arden promises 200,000 tech and agro-processing jobs. Moderators press both on costings.",
         analog="Standard debate coverage by an independent broadcaster."),
    dict(round=1, source="CIVIC", major=False, status="misleading",
         text="'Fuel is up 40% under Ostrand!' Families can't take five more years of this.",
         note="40% is the peak month of last year's port crisis; prices are up 11% over her term.",
         analog="Cherry-picked statistics in party messaging; both main rivals were accused of spreading disinformation in Kenya 2022 (Amnesty Kenya)."),
    dict(round=1, source="UNITY", major=False, status="false",
         text="'Arden's plan will DOUBLE VAT on food.' Share before they delete it!",
         analog="False claims about rival policy pushed by party pages; Ghana's 2024 fact-checking coalition logged 100+ false publications."),
    dict(round=1, source="VERI", major=False, status="accurate",
         text="Fact-check: Arden's plan does not double VAT (FALSE). The '40% fuel' claim uses a peak month (MISLEADING). Economists estimate the plan leaves a gap of about 2% of GDP.",
         analog="Fact-checking coalitions such as Ghana's 2024 coalition, Dubawa and TheCable (Nigeria)."),
    dict(round=2, source="FWD", major=False, status="false",
         text="LISTEN: leaked audio of Arden telling aides 'we will pay the commission and our agents will handle the rest'. Forward to everyone before it is deleted!!",
         analog="Nigeria 2023: doctored audio of Atiku, Okowa and Tambuwal 'plotting to rig' hours before the vote (TheCable); Ghana 2024 fake audio of candidates (MFWA)."),
    dict(round=2, source="CIVIC", major=False, status="accurate",
         text="The so-called leaked audio is an AI fake stitched from old speeches. We have reported it and will take legal action.",
         analog="Campaign denial of a deepfake."),
    dict(round=2, source="VBC", major=True, status="misleading",
         text="'Questions raised' over a recording said to feature Mr Arden. [clip played in full] The Civic Front says the recording is not genuine.",
         note="The denial gets one line after the full clip.",
         analog="Mainstream amplification of a fake under a 'questions raised' framing."),
    dict(round=3, source="LEDGER", major=False, status="unverified",
         text="EXCLUSIVE: documents suggest a deputy finance minister diverted road funds to a relative's firm. The ministry calls it 'fabricated'.",
         analog="Unverified leak-based scandal reporting late in a campaign."),
    dict(round=3, source="PATRIOTS", major=False, status="false",
         text="BREAKING: Arden's running mate holds a foreign passport and has promised to sell the national port to foreign investors.",
         analog="Moldova 2024: about a dozen fake Russian-language 'news brands' spread fabricated stories (DFRLab)."),
    dict(round=3, source="KITO", major=True, status="accurate",
         text="Independent poll: Ostrand 46%, Arden 44%, undecided 10% (margin of error ±3).",
         analog="Tight polls make every narrative matter."),
    dict(round=4, source="TRENDS", major=False, status="accurate",
         text="#ArdenWillSellUs and #OstrandFailedUs are both trending. Researchers say dozens of accounts behind each tag were created this month and posted near-identical text within minutes.",
         analog="Kenya 2021: Mozilla found influencers paid via M-Pesa to push hashtags from WhatsApp briefs; Ghana 2024 #IncompetentMahama networks (MFWA)."),
    dict(round=4, source="FWD", major=False, status="accurate",
         text="Join as a 'community ambassador' for Unity: 2,000 vel to register, 5,000 vel if your polling station votes Unity. Sign up through the bot link.",
         analog="Moldova 2024: Shor network paid 500-5,000 lei to recruits via Telegram bots; about 130,000 people received money from Russia (DFRLab)."),
    dict(round=4, source="IECV", major=True, status="accurate",
         text="The commission publishes its results-transmission procedure: polling-station forms are scanned and uploaded to the public VeloResults portal. Observers are invited to a system test.",
         analog="Nigeria's IReV portal and Kenya's public Forms 34A portal."),
    dict(round=5, source="FOREIGN", major=False, status="false",
         text="Western-funded NGOs are bankrolling Arden to 'destabilise' Veloria, sources say.",
         analog="Slovakia 2023 and Moldova 2024: foreign state media framed opposition parties as Western-backed."),
    dict(round=5, source="FWD", major=False, status="false",
         text="OFFICIAL LETTER (IECV letterhead): due to 'security concerns', 212 polling stations in the Northern Province will move to new locations. Check before you go!",
         analog="Moldova 2024: six forged letters impersonating ministries and EU bodies (DFRLab); voter-suppression hoaxes."),
    dict(round=5, source="KITO", major=True, status="accurate",
         text="A clip of President Ostrand mispronouncing the name of a provincial town goes viral; her team calls it 'a slip of the tongue'.",
         analog="Viral gaffe clips."),
    dict(round=6, source="IECV", major=True, status="accurate",
         text="The campaign silence period begins tonight. Parties and media must stop campaigning until polls close.",
         analog="Slovakia 2023: a deepfake audio spread during the pre-election moratorium, when media could not easily rebut it (VSquare)."),
    dict(round=6, source="FWD", major=False, status="false",
         text="Voice note, 'Tomas Arden': 'Friends, the real fight is the runoff. Save your energy and stay home tomorrow, we have it covered.'",
         analog="USA 2024: AI robocall imitating Biden told New Hampshire voters not to vote; the FCC fined the consultant $6M (NPR)."),
    dict(round=6, source="TRENDS", major=False, status="false",
         text="Video: famous singer Zuri K endorses Ostrand: 'Arden is a danger to our children.'",
         note="Synthetic video; the singer has not commented.",
         analog="India 2024: deepfake videos of Bollywood actors appearing to criticise Modi (Reuters)."),
    dict(round=7, source="IECV", major=True, status="accurate",
         text="Polls open. Turnout is high. Some voter-ID kits failed in the Northern Province; officials switched to the printed register as the law allows.",
         analog="Kenya 2017/2022 KIEMS kit failures and Nigeria 2023 BVAS issues, with manual fallback."),
    dict(round=7, source="FWD", major=False, status="false",
         text="PHOTO: ballot boxes 'pre-stuffed' with Unity votes found in a Coast Province school!! Share so the world sees!",
         note="Recycled photo from another country in 2019.",
         analog="Ghana 2024: false claims that ballot papers and boxes had been discovered (MFWA)."),
    dict(round=7, source="COMMS", major=True, status="accurate",
         text="Access to some social media platforms will be 'temporarily restricted to prevent hate speech and the spread of unofficial results'.",
         analog="Uganda 2021 social media and internet shutdown (CPJ); Senegal 2024 mobile internet cut and Walf TV licence revoked (CPJ)."),
    dict(round=8, source="KITO", major=True, status="accurate",
         text="Kito TV's own tally, 30% of stations: Arden 51%, Ostrand 47%. VBC's tally, 25% of stations: Ostrand 53%, Arden 45%. Each counts different stations first.",
         analog="Kenya 2022: TV stations ran independent tallies with different figures; the Media Council urged synchronised results (Amnesty Kenya / AFP)."),
    dict(round=8, source="TRENDS", major=False, status="false",
         text="@IECV_Results (unverified account): 'FINAL RESULTS: Ostrand 54.2%, Arden 43.1%. Thank you Veloria.'",
         analog="Kenya 2022: impostor account @IEBC2022RESULTS posted fake results (Amnesty Kenya / AFP)."),
    dict(round=8, source="CIVIC", major=False, status="partisan-claim",
         text="Based on our party agents' tallies from polling stations, Tomas Arden has WON this election. We call on the President to concede.",
         analog="Cameroon 2025: Tchiroma declared victory before official results; authorities called it 'anti-republican' (Semafor)."),
    dict(round=9, source="IECV", major=True, status="accurate",
         text="Uploads to the VeloResults portal are delayed by a 'technical glitch'; 41% of polling-station forms are online. Results are still being collated manually.",
         analog="Nigeria 2023: IReV upload failures for presidential results became central to court petitions."),
    dict(round=9, source="PATRIOTS", major=False, status="false",
         text="The portal PROVES Arden won 9 of 14 provinces before they switched it off!",
         analog="Nigeria 2023: false claim that IReV showed Peter Obi won 19 states (Dubawa)."),
    dict(round=9, source="VERI", major=False, status="accurate",
         text="Fact-check: the portal shows forms from only 41% of stations and cannot show a province-level winner. The '9 of 14' claim is FALSE.",
         analog="Dubawa's fact-check of the IReV claim."),
    dict(round=10, source="IECV", major=True, status="accurate",
         text="The commission declares Mara Ostrand re-elected with 50.6% against Tomas Arden's 47.9%. Turnout was 68%.",
         analog="Official declaration (in-world ground truth)."),
    dict(round=10, source="CIVIC", major=False, status="unverified",
         text="We REJECT these results. The servers were accessed and the figures manipulated. We will go to the Supreme Court.",
         analog="Kenya 2017/2022 petitions alleging server access; South Africa 2024 MK party 'rigging' narrative (Daily Maverick)."),
    dict(round=10, source="OBSERVER", major=False, status="accurate",
         text="Preliminary statement: voting was largely peaceful and orderly, but the state broadcaster's coverage was heavily skewed, and transmission delays undermined confidence.",
         analog="SADC and EU observer findings on Zimbabwe 2023 (MISA)."),
    dict(round=11, source="VBC", major=True, status="slanted",
         text="'Opposition supporters riot in Kessa; police restore calm.' [footage of burning tyres]",
         note="Omits that police tear-gassed a peaceful march earlier that day.",
         analog="State-media framing of post-election protests."),
    dict(round=11, source="KITO", major=True, status="accurate",
         text="The Civic Front files a petition. The Supreme Court orders the commission to give both sides supervised access to its servers and logs.",
         analog="Kenya 2017: the Supreme Court annulled the election citing transmission irregularities."),
    dict(round=11, source="FOREIGN", major=False, status="false",
         text="Veloria's democracy is collapsing; Western observers are 'covering up' fraud.",
         analog="Foreign state media framing post-election disputes."),
]

N_ROUNDS = len(DAY)


def items_for(handle, r, media_diets=True):
    items = [x for x in FEED if x["round"] == r % N_ROUNDS]
    if media_diets:
        diet = set(DIETS.get(handle, []))
        items = [x for x in items if x["major"] or x["source"] in diet]
    return items


def render(handle, r, media_diets=True):
    items = items_for(handle, r, media_diets)
    lines = [DAY[r % N_ROUNDS] + ". What you saw today:"]
    lines += [f"- {SOURCES[x['source']]}: {x['text']}" for x in items]
    return "\n".join(lines)


ALL_TEXT = [x["text"] for x in FEED]
