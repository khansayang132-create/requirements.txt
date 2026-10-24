cl import from "class-variance-authority" { cva }
cl import from "radix-ui" { Toggle as TogglePrimitive }
cl import from ...lib.utils { cn }

glob _toggleVariants: Any = cva(
    "hover:text-foreground aria-pressed:bg-muted focus-visible:border-ring focus-visible:ring-ring/50 aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive gap-1 rounded-md text-sm font-medium transition-[color,box-shadow] [&_svg:not([class*='size-'])]:size-4 group/toggle hover:bg-muted inline-flex items-center justify-center whitespace-nowrap outline-none focus-visible:ring-[3px] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
    {
        "variants": {
            "variant": {
                "default": "bg-transparent",
                "outline": "border-input hover:bg-muted border bg-transparent shadow-xs"
            },
            "size": {
                "default": "h-9 min-w-9 px-2",
                "sm": "h-8 min-w-8 px-1.5",
                "lg": "h-10 min-w-10 px-2.5"
            }
        },
        "defaultVariants": {
            "variant": "default",
            "size": "default"
        }
    }
);

cl {
    def:pub Toggle(props: Any) -> JsxElement {
        variant = props.variant or "default";
        size = props.size or "default";
        variantsFn = _toggleVariants;
        computedClass = cn(variantsFn.call(None, {"variant": variant, "size": size, "className": props.className}));
        return <TogglePrimitive.Root
            {...props}
            data-slot="toggle"
            className={computedClass}
        />;
    }

    def:pub toggleVariants() -> Any {
        return _toggleVariants;
    }
}
