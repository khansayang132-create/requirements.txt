export const cn = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(" ");
