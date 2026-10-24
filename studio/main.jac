"""LSKhan Studio: hooks, scripts, captions and series for LSKhan 🌏💞 Cinta Beda Negara.

Phone-first web app. The server half calls the AI through studio_ai.py, which reuses bot.py's
persona, prompts and OmniRoute routes. jaclang 0.16.7 listens on 0.0.0.0 whatever --host says,
so the walkers are reachable from the local network: every AI call is checked against
STUDIO_ACCESS_CODE in studio_ai.py, which fails closed when the code is unset.
"""

import from studio_ai { generate as ai_generate, status as ai_status }

walker:pub Generate {
    has kind: str,
        topic: str = "",
        angle: str = "",
        code: str = "";

    can run with Root entry {
        report ai_generate(self.kind, self.topic, self.angle, self.code);
    }
}

walker:pub AiStatus {
    has code: str = "";

    can run with Root entry {
        report ai_status(self.code);
    }
}

cl import from ".components.ui.button" { Button }
cl import from ".components.ui.card" { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter }
cl import from ".components.ui.badge" { Badge }
cl import from ".components.ui.textarea" { Textarea }
cl import from ".components.ui.input" { Input }
cl import from ".components.ui.field" { Field, FieldLabel, FieldDescription }
cl import from ".components.ui.tabs" { Tabs, TabsList, TabsTrigger, TabsContent }
cl import from ".components.ui.toggle-group" { ToggleGroup, ToggleGroupItem }
cl import from ".components.ui.checkbox" { Checkbox }
cl import from ".components.ui.alert" { Alert, AlertTitle, AlertDescription }
cl import from ".components.ui.spinner" { Spinner }
cl import from "@hugeicons/react" { HugeiconsIcon }
cl import from "@hugeicons/core-free-icons" { Copy01Icon, Tick02Icon, SparklesIcon }
cl import ".global.css";

cl {
    glob ANGLES: list = [
        {"value": "emosional", "label": "Emosional"},
        {"value": "lucu", "label": "Lucu"},
        {"value": "misteri", "label": "Misteri"},
        {"value": "budaya", "label": "Budaya"},
        {"value": "keluarga", "label": "Keluarga"},
        {"value": "realita", "label": "Realita"},
        {"value": "edukasi", "label": "Edukasi"},
        {"value": "debat", "label": "Debat"},
        {"value": "kontroversial", "label": "Kontroversial"},
        {"value": "islami", "label": "Islami"}
    ];

    glob TOOLS: list = [
        {
            "kind": "hook",
            "tab": "Hook",
            "title": "5 Hook Pembuka",
            "description": "Kalimat 1-2 detik pertama yang bikin orang berhenti scroll.",
            "placeholder": "Contoh: pertama kali makan bareng keluarga suami di Pakistan"
        },
        {
            "kind": "script",
            "tab": "Naskah",
            "title": "Naskah Video",
            "description": "HOOK → CERITA → TWIST → PAYOFF → PERTANYAAN, lengkap dengan teks layar dan B-roll.",
            "placeholder": "Ceritakan kejadiannya apa adanya. AI tidak akan menambah drama."
        },
        {
            "kind": "caption",
            "tab": "Caption",
            "title": "Caption & Hashtag",
            "description": "3 caption singkat yang bikin penasaran, 4-7 hashtag yang nyambung.",
            "placeholder": "Video ini tentang apa?"
        },
        {
            "kind": "series",
            "tab": "Series",
            "title": "Rencana Series",
            "description": "Pecah satu cerita jadi 3-5 part yang tetap seru walau ditonton sendiri.",
            "placeholder": "Tulis cerita lengkapnya di sini."
        }
    ];

    glob CHECKS: list = [
        "2 detik pertama bikin aku berhenti scroll?",
        "Ada alasan untuk nonton sampai habis?",
        "Setiap adegan memang perlu?",
        "Teks di layar terbaca jelas di HP?",
        "Suara jelas, tidak kalah dengan musik?",
        "Musik cocok dengan emosi ceritanya?",
        "Ceritanya terasa asli, bukan drama buatan?",
        "Ada alasan alami untuk komentar?",
        "Masih sesuai niche Indonesia × Pakistan?",
        "Aku sendiri akan terus nonton kalau muncul di FYP?"
    ];

    glob CODE_KEY: str = "lskhan-studio-code";

    def loadCode -> str {
        try {
            return localStorage.getItem(CODE_KEY) or "";
        } except Exception {
            return "";
        }
    }

    def saveCode(c: str) -> None {
        try {
            if c {
                localStorage.setItem(CODE_KEY, c);
            } else {
                localStorage.removeItem(CODE_KEY);
            }
        } except Exception {
            return;
        }
    }

    def:pub Generator(props: Any) -> JsxElement {
        tool = props.tool;
        has topic: str = "",
            angle: str = "",
            busy: bool = False,
            result: str = "",
            error: str = "",
            copied: bool = False;

        async def run -> None {
            busy = True;
            error = "";
            copied = False;
            response = root spawn Generate(kind=tool.kind, topic=topic, angle=angle, code=props.code);
            out = response.reports[0];
            if out.ok {
                result = out.text;
            } else {
                error = out.error;
            }
            busy = False;
        }

        def copyResult -> None {
            navigator.clipboard.writeText(result);
            copied = True;
        }

        return <div className="flex flex-col gap-4">
            <Card>
                <CardHeader>
                    <CardTitle>{tool.title}</CardTitle>
                    <CardDescription>{tool.description}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-5">
                    <Field>
                        <FieldLabel htmlFor={"topic-" + tool.kind}>Topik atau cerita</FieldLabel>
                        <Textarea
                            id={"topic-" + tool.kind}
                            rows={4}
                            maxLength={2000}
                            placeholder={tool.placeholder}
                            value={topic}
                            onChange={lambda(e: Any) -> None { topic = e.target.value; }}
                        />
                        <FieldDescription>{"Kosongkan kalau mau AI pilih topik segar."}</FieldDescription>
                    </Field>
                    <Field>
                        <FieldLabel>Arah konten</FieldLabel>
                        <ToggleGroup
                            type="single"
                            variant="outline"
                            size="sm"
                            spacing={2}
                            className="w-full flex-wrap gap-2"
                            value={angle}
                            onValueChange={lambda(v: Any) -> None { angle = v; }}
                        >
                            {[<ToggleGroupItem
                                key={a.value}
                                value={a.value}
                                variant="outline"
                                size="sm"
                                className="data-[state=on]:border-primary data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
                            >{a.label}</ToggleGroupItem> for a in ANGLES]}
                        </ToggleGroup>
                        <FieldDescription>{"Ganti-ganti arah supaya setiap video terasa baru."}</FieldDescription>
                    </Field>
                </CardContent>
                <CardFooter>
                    <Button className="w-full" size="lg" disabled={busy} onClick={lambda -> None { run(); }}>
                        {(<Spinner data-icon="inline-start" />) if busy else (<HugeiconsIcon icon={SparklesIcon} strokeWidth={2} data-icon="inline-start" />)}
                        {"Sedang menulis…" if busy else "Buat sekarang"}
                    </Button>
                </CardFooter>
            </Card>
            {(<Alert variant="destructive">
                <AlertTitle>Belum berhasil</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
            </Alert>) if error else None}
            {(<Card>
                <CardHeader>
                    <CardTitle>Hasil</CardTitle>
                    <CardDescription>{"Baca dulu, sesuaikan dengan kejadian aslinya."}</CardDescription>
                </CardHeader>
                <CardContent>
                    <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">{result}</div>
                </CardContent>
                <CardFooter>
                    <Button variant="outline" className="w-full" onClick={lambda -> None { copyResult(); }}>
                        <HugeiconsIcon icon={Tick02Icon if copied else Copy01Icon} strokeWidth={2} data-icon="inline-start" />
                        {"Tersalin" if copied else "Salin"}
                    </Button>
                </CardFooter>
            </Card>) if result else None}
        </div>;
    }

    def:pub QualityCheck(props: Any) -> JsxElement {
        has done: list = [];

        def toggle(i: int, checked: Any) -> None {
            if checked == True {
                done = done.concat([i]);
            } else {
                done = [d for d in done if d != i];
            }
        }

        ready = len(done) == len(CHECKS);

        return <Card>
            <CardHeader>
                <CardTitle>{"Cek Sebelum Upload"}</CardTitle>
                <CardDescription>{"Kalau ada yang belum, perbaiki dulu videonya."}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                {[<Field key={i} orientation="horizontal">
                    <Checkbox
                        id={"check-" + String(i)}
                        checked={done.includes(i)}
                        onCheckedChange={lambda(c: Any) -> None { toggle(i, c); }}
                    />
                    <FieldLabel htmlFor={"check-" + String(i)} className="font-normal">{q}</FieldLabel>
                </Field> for (i, q) in enumerate(CHECKS)]}
            </CardContent>
            <CardFooter>
                {(<Alert>
                    <AlertTitle>{"Siap upload 🌏💞"}</AlertTitle>
                    <AlertDescription>{"Penonton harus selesai menonton sambil berpikir: lalu apa yang terjadi?"}</AlertDescription>
                </Alert>) if ready else (<p className="text-sm text-muted-foreground">{String(len(done)) + " dari " + String(len(CHECKS)) + " sudah oke"}</p>)}
            </CardFooter>
        </Card>;
    }

    def:pub app -> JsxElement {
        has code: str = "",
            draft: str = "",
            status: Any = None,
            checking: bool = True;

        async def check(c: str) -> None {
            checking = True;
            response = root spawn AiStatus(code=c);
            st = response.reports[0];
            status = st;
            if st.access {
                code = c;
                saveCode(c);
            }
            checking = False;
        }

        def lock -> None {
            saveCode("");
            code = "";
            draft = "";
            status = None;
        }

        async can with entry {
            await check(loadCode());
        }

        unlocked = Boolean(status) and status.access;

        return <div className="min-h-screen bg-background text-foreground">
            <header className="border-b border-border">
                <div className="mx-auto flex max-w-xl items-center justify-between gap-3 pt-4 pr-4 pb-4 pl-4">
                    <div className="flex flex-col">
                        <h1 className="text-lg font-bold">LSKhan Studio</h1>
                        <p className="text-sm text-muted-foreground">{"🌏💞 Cinta Beda Negara"}</p>
                    </div>
                    {(<div className="flex items-center gap-2">
                        <Badge variant={"secondary" if status.ai else "destructive"}>{"AI siap" if status.ai else "AI belum diatur"}</Badge>
                        <Button variant="ghost" size="sm" onClick={lambda -> None { lock(); }}>Kunci</Button>
                    </div>) if unlocked else None}
                </div>
            </header>
            <main className="mx-auto max-w-xl pt-5 pr-4 pb-16 pl-4">
                {(<Tabs defaultValue="hook" className="gap-4">
                    <TabsList className="w-full">
                        {[<TabsTrigger key={t.kind} value={t.kind}>{t.tab}</TabsTrigger> for t in TOOLS]}
                        <TabsTrigger value="check">Cek</TabsTrigger>
                    </TabsList>
                    {[<TabsContent key={t.kind} value={t.kind}><Generator tool={t} code={code} /></TabsContent> for t in TOOLS]}
                    <TabsContent value="check"><QualityCheck /></TabsContent>
                </Tabs>) if unlocked else (<Card>
                    <CardHeader>
                        <CardTitle>Buka Studio</CardTitle>
                        <CardDescription>{"Masukkan kode akses dari STUDIO_ACCESS_CODE di .env. HP ini akan mengingatnya."}</CardDescription>
                    </CardHeader>
                    <CardContent className="flex flex-col gap-4">
                        <Field>
                            <FieldLabel htmlFor="access-code">Kode akses</FieldLabel>
                            <Input
                                id="access-code"
                                type="password"
                                autoComplete="current-password"
                                value={draft}
                                onChange={lambda(e: Any) -> None { draft = e.target.value; }}
                            />
                        </Field>
                        {(<Alert variant="destructive">
                            <AlertTitle>Belum bisa dibuka</AlertTitle>
                            <AlertDescription>{status.error}</AlertDescription>
                        </Alert>) if (Boolean(status) and Boolean(status.error) and (status.locked or Boolean(draft))) else None}
                    </CardContent>
                    <CardFooter>
                        <Button className="w-full" size="lg" disabled={checking or not draft} onClick={lambda -> None { check(draft); }}>
                            {(<Spinner data-icon="inline-start" />) if checking else None}
                            Buka
                        </Button>
                    </CardFooter>
                </Card>)}
            </main>
        </div>;
    }
}
