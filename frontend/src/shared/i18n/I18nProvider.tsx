import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { MESSAGES } from './messages.ts';
import type { Lang, Messages } from './messages.ts';

const KEY = 'drawmentle:lang';

type I18n = { lang: Lang; m: Messages; setLang: (lang: Lang) => void };

const I18nContext = createContext<I18n>({ lang: 'ko', m: MESSAGES.ko, setLang: () => {} });

function savedLang(): Lang {
  try {
    return window.localStorage.getItem(KEY) === 'en' ? 'en' : 'ko';
  } catch {
    return 'ko'; // storage blocked: Korean default, the switch still works for this page
  }
}

// Korean by default; the viewer's choice is remembered in this browser only.
export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(savedLang);
  const m = MESSAGES[lang];

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = m.title;
  }, [lang, m]);

  function setLang(next: Lang) {
    setLangState(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // not persisted; fine for this visit
    }
  }

  return <I18nContext.Provider value={{ lang, m, setLang }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  return useContext(I18nContext);
}
