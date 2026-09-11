/**
 * The blocking inline script that applies the display switches before first
 * paint, and the CSP hash that allows it.
 *
 * It lives here rather than inside `ThemeScript.tsx` because two very
 * different places need it: the component renders it, and `middleware.ts`
 * has to name it in `script-src`. A second copy of the string in the CSP
 * would be a hash that silently stops matching the day someone edits the
 * script — a blank flash of the wrong palette, on the one code path that
 * exists to prevent exactly that.
 *
 * The nonce Next.js mints per request covers Next's own inline bootstrap,
 * but not this: the nonce is only knowable inside a dynamically rendered
 * tree, and the locale layout is deliberately static (`generateStaticParams`
 * + `setRequestLocale`). A hash is the standard answer for a script whose
 * text is fixed at build time, and it keeps the layout static.
 */
export const THEME_SCRIPT = `(function(){try{
    var r=document.documentElement;
    var raw=localStorage.getItem('alppy.display');
    if(!raw)return;
    var p=JSON.parse(raw);
    ['theme','contrast','motion','calm','discreet'].forEach(function(k){
      var v=p&&p[k];
      if(v){r.setAttribute('data-'+k,v);}else{r.removeAttribute('data-'+k);}
    });
  }catch(e){}})();`;

/**
 * `sha256-<base64>` over `THEME_SCRIPT`, as a `script-src` source expression.
 *
 * Committed rather than computed: the middleware runs in the edge runtime,
 * where hashing is only available asynchronously, and re-deriving a constant
 * on every request to a value that can only change at build time is work for
 * nothing. `theme-script.test.ts` recomputes it and fails if the two drift,
 * so the constant cannot go stale without the suite saying so.
 */
export const THEME_SCRIPT_CSP_HASH = "'sha256-BELUbTYmaNn5YzkKSL4dbtPKLopklhC2I3lPgcwwwM0='";
