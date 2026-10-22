#!/usr/bin/env bash
# 把 _build 分片拼成单文件原型（内联 CSS/JS，双击即可打开，无外部依赖）
set -e
cd "$(dirname "$0")"
{
  cat _build/00-head.html
  cat _build/01-tokens.css
  echo ""
  echo "/* ===== 02 base ===== */"
  cat _build/02-base.css
  echo ""
  echo "/* ===== 03 pages ===== */"
  cat _build/03-pages.css
  echo ""
  echo "/* ===== 04 extra ===== */"
  cat _build/04-extra.css
  echo "</style>"
  echo "</head>"
  echo "<body>"
  cat _build/10-body.html
  cat _build/05-data.js
  echo ""
  cat _build/06-charts.js
  echo ""
  cat _build/07-pages.js
  echo ""
  cat _build/08-pages2.js
  echo ""
  cat _build/09-app.js
  echo "</script>"
  echo "</body>"
  echo "</html>"
} > index.html
node -e "
const fs=require('fs');
const s=fs.readFileSync('index.html','utf8');
const i=s.lastIndexOf('<script>')+8, j=s.lastIndexOf('</script>');
try{ new Function(s.slice(i,j)); console.log('✓ JS 语法通过'); }catch(e){ console.log('✗ JS 语法错误:', e.message); process.exit(1); }
"
echo "✓ 构建完成: index.html ($(wc -c < index.html) bytes)"
