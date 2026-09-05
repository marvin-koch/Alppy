/**
 * Applies the four display switches before first paint.
 *
 * This has to be a blocking inline script. Setting the attributes in an effect
 * would paint the light palette first and then swap, which is the flash every
 * dark-mode implementation is judged by.
 *
 * `data-theme` absent is a real, third state — "follow the system" — and is not
 * a synonym for light. So the script only ever *sets* an attribute the teacher
 * has actually chosen, and removes it otherwise.
 */
export function ThemeScript() {
  const script = `(function(){try{
    var r=document.documentElement;
    var raw=localStorage.getItem('alppy.display');
    if(!raw)return;
    var p=JSON.parse(raw);
    ['theme','contrast','motion','calm'].forEach(function(k){
      var v=p&&p[k];
      if(v){r.setAttribute('data-'+k,v);}else{r.removeAttribute('data-'+k);}
    });
  }catch(e){}})();`;
  return <script dangerouslySetInnerHTML={{ __html: script }} />;
}
