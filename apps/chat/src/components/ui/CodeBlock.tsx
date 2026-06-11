"use client";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { useTheme } from "next-themes";
import { Fragment, useLayoutEffect, useState } from "react";
import type { JSX, ReactNode } from "react";
import { codeToHast } from "shiki/bundle/web";
import { safe } from "ts-safe";
import { jsx, jsxs } from "react/jsx-runtime";
import { cn } from "lib/utils";

export function CodeBlock({
  code,
  lang,
  fallback,
  className,
  showLineNumbers = true,
}: {
  code?: string;
  lang: string;
  fallback?: ReactNode;
  className?: string;
  showLineNumbers?: boolean;
}) {
  const { theme } = useTheme();

  const [component, setComponent] = useState<JSX.Element | null>(null);

  useLayoutEffect(() => {
    safe()
      .map(async () => {
        const out = await codeToHast(code || "", {
          lang: lang,
          theme: theme == "dark" ? "github-dark" : "github-light",
        });
        return toJsxRuntime(out, {
          Fragment,
          jsx,
          jsxs,
          components: {
            pre: (props) => (
              <pre
                {...props}
                lang={lang}
                style={undefined}
                className={cn(props.className, className)}
              >
                <div className={cn(showLineNumbers && "pl-12 relative")}>
                  {showLineNumbers && (
                    <div className="absolute left-0 top-0 w-6 flex flex-col select-none text-right text-muted-foreground">
                      {code?.split("\n").map((_, index) => (
                        <span key={index}>{index + 1}</span>
                      ))}
                    </div>
                  )}
                  {props.children}
                </div>
              </pre>
            ),
          },
        }) as JSX.Element;
      })
      .ifOk(setComponent)
      // Shiki errors are silent in production; without a reset we'd hold
      // the previous render's highlighted output instead of falling back.
      .ifFail(() => setComponent(null));
  }, [theme, lang, code]);

  if (!code) return fallback;

  // Plain-text fallback while highlighting loads (or if Shiki errored on
  // this input). Without this the block would render empty.
  return (
    component ?? (
      <pre className={className} lang={lang}>
        <code>{code}</code>
      </pre>
    )
  );
}
