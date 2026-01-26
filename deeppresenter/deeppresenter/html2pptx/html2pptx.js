/**
 * html2pptx - Convert HTML slide to pptxgenjs slide with positioned elements
 * Originally based on Anthropic Skills, modified and enhanced by PPTAgent team
 *
 * USAGE:
 *   const pptx = new pptxgen();
 *   pptx.layout = 'LAYOUT_16x9';  // Must match HTML body dimensions
 *
 *   const { slide, placeholders } = await html2pptx('slide.html', pptx);
 *   slide.addChart(pptx.charts.LINE, data, placeholders[0]);
 *
 *   await pptx.writeFile('output.pptx');
 *
 * FEATURES:
 *   - Converts HTML to PowerPoint with accurate positioning
 *   - Supports text, images, shapes, tables, and bullet lists
 *   - Extracts placeholder elements (class="placeholder") with positions
 *   - Handles CSS gradients, borders, and margins
 *
 * VALIDATION:
 *   - Uses body width/height from HTML for viewport sizing
 *   - Throws error if HTML dimensions don't match presentation layout
 *   - Throws error if content overflows body (with overflow details)
 *
 * RETURNS:
 *   { slide, placeholders } where placeholders is an array of { id, x, y, w, h }
 */

const { chromium } = require('playwright');
const fs = require('fs');
const os = require('node:os');
const path = require('path');
const sharp = require('sharp');

// Conversion constants
const PT_PER_PX = 0.75;  // Points per pixel
const PX_PER_IN = 96;    // Pixels per inch (standard screen DPI)
const EMU_PER_IN = 914400;  // English Metric Units per inch (PowerPoint internal unit)

/**
 * Get body dimensions and check for content overflow
 * @returns {Object} Body dimensions with width, height, scrollWidth, scrollHeight, and any overflow errors
 */
async function getBodyDimensions(page) {
  const bodyDimensions = await page.evaluate(() => {
    const body = document.body;
    const style = window.getComputedStyle(body);

    return {
      width: parseFloat(style.width),
      height: parseFloat(style.height),
      scrollWidth: body.scrollWidth,
      scrollHeight: body.scrollHeight
    };
  });

  const errors = [];
  const widthOverflowPx = Math.max(0, bodyDimensions.scrollWidth - bodyDimensions.width - 1);
  const heightOverflowPx = Math.max(0, bodyDimensions.scrollHeight - bodyDimensions.height - 1);

  const widthOverflowPt = widthOverflowPx * PT_PER_PX;
  const heightOverflowPt = heightOverflowPx * PT_PER_PX;

  if (widthOverflowPt > 0 || heightOverflowPt > 0) {
    const directions = [];
    if (widthOverflowPt > 0) directions.push(`${widthOverflowPt.toFixed(1)}pt horizontally`);
    if (heightOverflowPt > 0) directions.push(`${heightOverflowPt.toFixed(1)}pt vertically`);
    const reminder = heightOverflowPt > 0 ? ' (Remember: leave 0.5" margin at bottom of slide)' : '';
    errors.push(`HTML content overflows body by ${directions.join(' and ')}${reminder}`);
  }

  return { ...bodyDimensions, errors };
}

/**
 * Validate that HTML dimensions match the presentation layout
 * @returns {Array<string>} Array of validation error messages
 */
function validateDimensions(bodyDimensions, pres) {
  const errors = [];
  const widthInches = bodyDimensions.width / PX_PER_IN;
  const heightInches = bodyDimensions.height / PX_PER_IN;

  if (pres.presLayout) {
    const layoutWidth = pres.presLayout.width / EMU_PER_IN;
    const layoutHeight = pres.presLayout.height / EMU_PER_IN;

    if (Math.abs(layoutWidth - widthInches) > 0.1 || Math.abs(layoutHeight - heightInches) > 0.1) {
      errors.push(
        `HTML dimensions (${widthInches.toFixed(1)}" × ${heightInches.toFixed(1)}") ` +
        `don't match presentation layout (${layoutWidth.toFixed(1)}" × ${layoutHeight.toFixed(1)}")`
      );
    }
  }
  return errors;
}

/**
 * Validate text box positions to ensure proper bottom margin
 * PowerPoint requires 0.5" margin from bottom edge for proper rendering
 */
function validateTextBoxPosition(slideData, bodyDimensions) {
  const errors = [];
  const slideHeightInches = bodyDimensions.height / PX_PER_IN;
  const minBottomMargin = 0.5; // 0.5 inches from bottom

  for (const el of slideData.elements) {
    // Check text elements (p, h1-h6, list)
    if (['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'list'].includes(el.type)) {
      const fontSize = el.style?.fontSize || 0;
      const bottomEdge = el.position.y + el.position.h;
      const distanceFromBottom = slideHeightInches - bottomEdge;

      if (fontSize > 12 && distanceFromBottom < minBottomMargin) {
        const getText = () => {
          if (typeof el.text === 'string') return el.text;
          if (Array.isArray(el.text)) return el.text.find(t => t.text)?.text || '';
          if (Array.isArray(el.items)) return el.items.find(item => item.text)?.text || '';
          return '';
        };
        const textPrefix = getText().substring(0, 50) + (getText().length > 50 ? '...' : '');

        errors.push(
          `Text box "${textPrefix}" ends too close to bottom edge ` +
          `(${distanceFromBottom.toFixed(2)}" from bottom, minimum ${minBottomMargin}" required)`
        );
      }
    }
  }

  return errors;
}

/**
 * Add background (image or color) to the slide
 */
async function addBackground(slideData, targetSlide, tmpDir) {
  if (slideData.background.type === 'image' && slideData.background.path) {
    let imagePath = slideData.background.path.startsWith('file://')
      ? slideData.background.path.replace('file://', '')
      : slideData.background.path;
    targetSlide.background = { path: imagePath };
  } else if (slideData.background.type === 'color' && slideData.background.value) {
    targetSlide.background = { color: slideData.background.value };
  }
}

/**
 * Rasterize CSS gradients, shadows, and complex styles to images
 * PowerPoint doesn't natively support CSS gradients and some advanced styling,
 * so we render them in browser and capture as PNG images
 */
async function rasterizeGradients(page, slideData, bodyDimensions, tmpDir) {
  const outDir = tmpDir || process.env.TMPDIR || '/tmp';
  fs.mkdirSync(outDir, { recursive: true });

  const makeId = () => `__html2pptx_gradient_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const makePath = () => path.join(outDir, `html2pptx-bg-${Date.now()}-${Math.random().toString(16).slice(2)}.png`);

  await page.evaluate(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.backgroundImage = 'none';
    document.body.style.backgroundColor = 'transparent';
    document.body.innerHTML = '';
  });

  /**
   * Calculate shadow extent for screenshot area expansion
   * Shadow extends by blur+spread radius in all directions, offset by shadow position
   */
  const parseShadowExtent = (boxShadow) => {
    if (!boxShadow || boxShadow === 'none') return { left: 0, right: 0, top: 0, bottom: 0 };

    // Extract numeric values (offset-x, offset-y, blur, spread)
    const parts = boxShadow.match(/([-\d.]+)px/g);
    if (!parts || parts.length < 2) return { left: 0, right: 0, top: 0, bottom: 0 };

    const offsetX = parseFloat(parts[0]);
    const offsetY = parseFloat(parts[1]);
    const blur = parts.length > 2 ? parseFloat(parts[2]) : 0;
    const spread = parts.length > 3 ? parseFloat(parts[3]) : 0;

    // Shadow extends: blur radius + spread on each side, adjusted by offset
    const extent = blur + spread;
    return {
      left: Math.max(0, extent - offsetX),
      right: Math.max(0, extent + offsetX),
      top: Math.max(0, extent - offsetY),
      bottom: Math.max(0, extent + offsetY)
    };
  };

  /**
   * Calculate text shadow extent for multiple shadows
   * Handles comma-separated shadow values and returns maximum extent
   */
  const parseTextShadowExtent = (textShadow) => {
    if (!textShadow || textShadow === 'none' || textShadow === 'normal') {
      return { left: 0, right: 0, top: 0, bottom: 0 };
    }

    const shadows = textShadow.split(/,(?![^(]*\))/);
    const extents = { left: 0, right: 0, top: 0, bottom: 0 };

    shadows.forEach((shadow) => {
      const parts = shadow.trim().match(/([-\d.]+)px/g);
      if (!parts || parts.length < 2) return;
      const offsetX = parseFloat(parts[0]);
      const offsetY = parseFloat(parts[1]);
      const blur = parts.length > 2 ? parseFloat(parts[2]) : 0;
      const extent = blur;
      extents.left = Math.max(extents.left, Math.max(0, extent - offsetX));
      extents.right = Math.max(extents.right, Math.max(0, extent + offsetX));
      extents.top = Math.max(extents.top, Math.max(0, extent - offsetY));
      extents.bottom = Math.max(extents.bottom, Math.max(0, extent + offsetY));
    });

    return extents;
  };

  /**
   * Render a background element with CSS styles as a PNG image
   * Handles gradients, colors, shadows, and border-radius
   */
  const renderBackground = async (style, widthPx, heightPx, leftPx = 0, topPx = 0) => {
    const id = makeId();
    const shadowExtent = parseShadowExtent(style.boxShadow);
    const hasSignificantShadow = shadowExtent.left + shadowExtent.right + shadowExtent.top + shadowExtent.bottom > 0;

    const expandedWidth = widthPx + shadowExtent.left + shadowExtent.right;
    const expandedHeight = heightPx + shadowExtent.top + shadowExtent.bottom;
    const expandedLeft = leftPx - shadowExtent.left;
    const expandedTop = topPx - shadowExtent.top;

    await page.evaluate(({ id, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, style }) => {
      const el = document.createElement('div');
      el.id = id;
      el.style.position = 'fixed';
      el.style.left = `${expandedLeft + shadowExtent.left}px`;
      el.style.top = `${expandedTop + shadowExtent.top}px`;
      el.style.width = `${widthPx}px`;
      el.style.height = `${heightPx}px`;
      if (style.backgroundColor) el.style.backgroundColor = style.backgroundColor;
      if (style.backgroundImage) el.style.backgroundImage = style.backgroundImage;
      el.style.backgroundRepeat = style.backgroundRepeat || 'no-repeat';
      el.style.backgroundSize = style.backgroundSize || 'auto';
      el.style.backgroundPosition = style.backgroundPosition || '0% 0%';
      if (style.borderRadius) el.style.borderRadius = style.borderRadius;
      if (style.boxShadow && style.boxShadow !== 'none') el.style.boxShadow = style.boxShadow;
      el.style.pointerEvents = 'none';
      el.style.zIndex = '2147483647';
      document.body.appendChild(el);
    }, { id, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, style });

    const filePath = makePath();
    if (hasSignificantShadow) {
      await page.screenshot({
        path: filePath,
        omitBackground: true,
        clip: {
          x: Math.max(0, expandedLeft),
          y: Math.max(0, expandedTop),
          width: expandedWidth,
          height: expandedHeight
        }
      });
    } else {
      const handle = await page.$(`#${id}`);
      await handle.screenshot({ path: filePath, omitBackground: true });
    }
    await page.evaluate((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    }, id);
    return { filePath, shadowExtent, hasSignificantShadow };
  };

  /**
   * Render an image element with applied CSS styles (object-fit, filters, shadows) as PNG
   */
  const renderImage = async (src, style, widthPx, heightPx, leftPx = 0, topPx = 0) => {
    const id = makeId();
    const shadowExtent = parseShadowExtent(style.boxShadow);
    const hasSignificantShadow = shadowExtent.left + shadowExtent.right + shadowExtent.top + shadowExtent.bottom > 0;

    const expandedLeft = leftPx - shadowExtent.left;
    const expandedTop = topPx - shadowExtent.top;
    const expandedWidth = widthPx + shadowExtent.left + shadowExtent.right;
    const expandedHeight = heightPx + shadowExtent.top + shadowExtent.bottom;

    await page.evaluate(({ id, src, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, style }) => {
      const img = document.createElement('img');
      img.id = id;
      img.src = src;
      img.style.position = 'fixed';
      // Position image within the expanded area, leaving room for shadow
      img.style.left = `${expandedLeft + shadowExtent.left}px`;
      img.style.top = `${expandedTop + shadowExtent.top}px`;
      img.style.width = `${widthPx}px`;
      img.style.height = `${heightPx}px`;
      img.style.objectFit = style.objectFit || 'fill';
      img.style.objectPosition = style.objectPosition || '50% 50%';
      if (style.filter && style.filter !== 'none') img.style.filter = style.filter;
      if (style.borderRadius) img.style.borderRadius = style.borderRadius;
      if (style.boxShadow && style.boxShadow !== 'none') img.style.boxShadow = style.boxShadow;
      img.style.pointerEvents = 'none';
      img.style.zIndex = '2147483647';
      document.body.appendChild(img);
    }, { id, src, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, style });

    await page.waitForFunction((id) => {
      const el = document.getElementById(id);
      return el && el.complete;
    }, id);

    const filePath = makePath();
    if (hasSignificantShadow) {
      await page.screenshot({
        path: filePath,
        omitBackground: true,
        clip: {
          x: Math.max(0, expandedLeft),
          y: Math.max(0, expandedTop),
          width: expandedWidth,
          height: expandedHeight
        }
      });
    } else {
      const handle = await page.$(`#${id}`);
      await handle.screenshot({ path: filePath, omitBackground: true });
    }
    await page.evaluate((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    }, id);
    return { filePath, shadowExtent, hasSignificantShadow };
  };

  /**
   * Render text with CSS text-shadow effects as PNG image
   * Handles both simple strings and arrays of formatted text runs
   */
  const renderText = async (text, style, widthPx, heightPx, leftPx = 0, topPx = 0) => {
    const id = makeId();
    const shadowExtent = parseTextShadowExtent(style.textShadow);
    const hasSignificantShadow = shadowExtent.left + shadowExtent.right + shadowExtent.top + shadowExtent.bottom > 0;

    const expandedLeft = leftPx - shadowExtent.left;
    const expandedTop = topPx - shadowExtent.top;
    const expandedWidth = widthPx + shadowExtent.left + shadowExtent.right;
    const expandedHeight = heightPx + shadowExtent.top + shadowExtent.bottom;

    await page.evaluate(
      ({ id, text, style, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, ptPerPx }) => {
        const toCssColor = (hex, transparency) => {
          if (!hex) return null;
          const clean = hex.startsWith('#') ? hex.slice(1) : hex;
          if (clean.length !== 6) return null;
          const r = parseInt(clean.slice(0, 2), 16);
          const g = parseInt(clean.slice(2, 4), 16);
          const b = parseInt(clean.slice(4, 6), 16);
          const alpha = transparency != null ? (100 - transparency) / 100 : 1;
          return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        };

        const ptToPx = (pt) => (typeof pt === 'number' ? pt / ptPerPx : null);

        const container = document.createElement('div');
        container.id = id;
        container.style.position = 'fixed';
        container.style.left = `${expandedLeft + shadowExtent.left}px`;
        container.style.top = `${expandedTop + shadowExtent.top}px`;
        container.style.width = `${widthPx}px`;
        container.style.height = `${heightPx}px`;
        container.style.pointerEvents = 'none';
        container.style.zIndex = '2147483647';
        container.style.boxSizing = 'border-box';
        container.style.display = 'flex';

        if (style.valign === 'middle') {
          container.style.alignItems = 'center';
        } else if (style.valign === 'bottom') {
          container.style.alignItems = 'flex-end';
        } else {
          container.style.alignItems = 'flex-start';
        }

        const textEl = document.createElement('div');
        textEl.style.width = '100%';
        textEl.style.boxSizing = 'border-box';
        textEl.style.whiteSpace = 'pre-wrap';
        textEl.style.backgroundColor = 'transparent';

        const color = toCssColor(style.color, style.transparency);
        if (color) textEl.style.color = color;
        if (style.fontFace) textEl.style.fontFamily = style.fontFace;
        if (style.fontWeight && style.fontWeight !== 'normal') textEl.style.fontWeight = style.fontWeight;
        if (style.bold && !style.fontWeight) textEl.style.fontWeight = 'bold';
        if (style.italic) textEl.style.fontStyle = 'italic';
        if (style.underline) textEl.style.textDecoration = 'underline';
        if (style.align) textEl.style.textAlign = style.align;
        if (style.letterSpacing && style.letterSpacing !== 'normal') textEl.style.letterSpacing = style.letterSpacing;
        if (style.textShadow && style.textShadow !== 'none') textEl.style.textShadow = style.textShadow;

        const fontSizePx = ptToPx(style.fontSize);
        if (fontSizePx) textEl.style.fontSize = `${fontSizePx}px`;
        const lineHeightPx = ptToPx(style.lineSpacing);
        if (lineHeightPx) textEl.style.lineHeight = `${lineHeightPx}px`;

        if (Array.isArray(style.margin) && style.margin.length === 4) {
          const paddingTop = ptToPx(style.margin[3]) || 0;
          const paddingRight = ptToPx(style.margin[1]) || 0;
          const paddingBottom = ptToPx(style.margin[2]) || 0;
          const paddingLeft = ptToPx(style.margin[0]) || 0;
          textEl.style.padding = `${paddingTop}px ${paddingRight}px ${paddingBottom}px ${paddingLeft}px`;
        }

        const appendTextWithBreaks = (parent, value) => {
          const parts = value.split('\n');
          parts.forEach((part, idx) => {
            if (part.length > 0) parent.appendChild(document.createTextNode(part));
            if (idx < parts.length - 1) parent.appendChild(document.createElement('br'));
          });
        };

        if (Array.isArray(text)) {
          text.forEach((run) => {
            if (!run || typeof run.text !== 'string') return;
            const span = document.createElement('span');
            if (run.options) {
              const runColor = toCssColor(run.options.color, run.options.transparency);
              if (runColor) span.style.color = runColor;
              if (run.options.bold) span.style.fontWeight = 'bold';
              if (run.options.italic) span.style.fontStyle = 'italic';
              if (run.options.underline) span.style.textDecoration = 'underline';
              if (typeof run.options.fontSize === 'number') {
                const runFontSizePx = ptToPx(run.options.fontSize);
                if (runFontSizePx) span.style.fontSize = `${runFontSizePx}px`;
              }
            }
            appendTextWithBreaks(span, run.text);
            textEl.appendChild(span);
            if (run.options && run.options.breakLine) {
              textEl.appendChild(document.createElement('br'));
            }
          });
        } else if (typeof text === 'string') {
          appendTextWithBreaks(textEl, text);
        }

        container.appendChild(textEl);
        document.body.appendChild(container);
      },
      { id, text, style, widthPx, heightPx, expandedLeft, expandedTop, shadowExtent, ptPerPx: PT_PER_PX }
    );

    const filePath = makePath();
    if (hasSignificantShadow) {
      await page.screenshot({
        path: filePath,
        omitBackground: true,
        clip: {
          x: Math.max(0, expandedLeft),
          y: Math.max(0, expandedTop),
          width: expandedWidth,
          height: expandedHeight
        }
      });
    } else {
      const handle = await page.$(`#${id}`);
      await handle.screenshot({ path: filePath, omitBackground: true });
    }
    await page.evaluate((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    }, id);
    return { filePath, shadowExtent, hasSignificantShadow };
  };

  /**
   * Render SVG markup as PNG image
   * PowerPoint doesn't natively support inline SVG
   */
  const renderSvg = async (svgMarkup, widthPx, heightPx, leftPx = 0, topPx = 0) => {
    const id = makeId();
    await page.evaluate(({ id, svgMarkup, widthPx, heightPx, leftPx, topPx }) => {
      const container = document.createElement('div');
      container.id = id;
      container.style.position = 'fixed';
      container.style.left = `${leftPx}px`;
      container.style.top = `${topPx}px`;
      container.style.width = `${widthPx}px`;
      container.style.height = `${heightPx}px`;
      container.style.pointerEvents = 'none';
      container.style.zIndex = '2147483647';
      container.innerHTML = svgMarkup;
      document.body.appendChild(container);

      const svg = container.querySelector('svg');
      if (svg) {
        svg.setAttribute('width', `${widthPx}px`);
        svg.setAttribute('height', `${heightPx}px`);
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.display = 'block';
      }
    }, { id, svgMarkup, widthPx, heightPx, leftPx, topPx });

    const handle = await page.$(`#${id}`);
    const filePath = makePath();
    await handle.screenshot({ path: filePath, omitBackground: true });
    await page.evaluate((id) => {
      const el = document.getElementById(id);
      if (el) el.remove();
    }, id);
    return filePath;
  };

  // Process slide background (convert gradients/CSS to images)
  if (slideData.background && slideData.background.type === 'css') {
    const { filePath } = await renderBackground(
      slideData.background.style || {},
      Math.round(bodyDimensions.width),
      Math.round(bodyDimensions.height),
      0,
      0
    );
    slideData.background = { type: 'image', path: filePath };
  } else if (slideData.background && slideData.background.type === 'gradient') {
    const { filePath } = await renderBackground(
      {
        ...(slideData.background.style || {}),
        backgroundImage: slideData.background.value
      },
      Math.round(bodyDimensions.width),
      Math.round(bodyDimensions.height),
      0,
      0
    );
    slideData.background = { type: 'image', path: filePath };
  }

  for (const el of slideData.elements) {
    if (el.type === 'bgImage') {
      // Render background DIVs with gradients/shadows as images
      const widthPx = Math.round(el.position.w * PX_PER_IN);
      const heightPx = Math.round(el.position.h * PX_PER_IN);
      const leftPx = Math.round(el.position.x * PX_PER_IN);
      const topPx = Math.round(el.position.y * PX_PER_IN);
      const { filePath, shadowExtent, hasSignificantShadow } = await renderBackground(el.style || {}, widthPx, heightPx, leftPx, topPx);
      el.type = 'image';
      el.src = filePath;
      if (hasSignificantShadow) {
        el.position.x -= shadowExtent.left / PX_PER_IN;
        el.position.y -= shadowExtent.top / PX_PER_IN;
        el.position.w += (shadowExtent.left + shadowExtent.right) / PX_PER_IN;
        el.position.h += (shadowExtent.top + shadowExtent.bottom) / PX_PER_IN;
      }
      delete el.style;
    } else if (el.type === 'image' && el.style) {
      // Check if image needs rasterization (SVG, object-fit, border-radius, filters, shadows)
      const isSvgImage = typeof el.src === 'string'
        && (el.src.toLowerCase().endsWith('.svg') || el.src.startsWith('data:image/svg'));
      const objectFit = el.style.objectFit || 'fill';
      const objectPosition = el.style.objectPosition || '50% 50%';
      const borderRadius = el.style.borderRadius;
      const filter = el.style.filter;
      const boxShadow = el.style.boxShadow;
      const hasBoxShadow = boxShadow && boxShadow !== 'none';
      const shouldRender = isSvgImage
        || objectFit !== 'fill'
        || objectPosition !== '50% 50%'
        || borderRadius
        || (filter && filter !== 'none')
        || hasBoxShadow;
      if (shouldRender) {
        const widthPx = Math.round(el.position.w * PX_PER_IN);
        const heightPx = Math.round(el.position.h * PX_PER_IN);
        const leftPx = Math.round(el.position.x * PX_PER_IN);
        const topPx = Math.round(el.position.y * PX_PER_IN);
        const { filePath, shadowExtent, hasSignificantShadow } = await renderImage(el.src, el.style, widthPx, heightPx, leftPx, topPx);
        el.src = filePath;
        if (hasSignificantShadow) {
          el.position.x -= shadowExtent.left / PX_PER_IN;
          el.position.y -= shadowExtent.top / PX_PER_IN;
          el.position.w += (shadowExtent.left + shadowExtent.right) / PX_PER_IN;
          el.position.h += (shadowExtent.top + shadowExtent.bottom) / PX_PER_IN;
        }
      }
      delete el.style;
    } else if (['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div'].includes(el.type)
      && el.style
      && el.style.textShadow
      && el.style.textShadow !== 'none'
      && el.style.textShadow !== 'normal') {
      // Render text with text-shadow as image (PowerPoint doesn't support CSS text-shadow)
      const widthPx = Math.round(el.position.w * PX_PER_IN);
      const heightPx = Math.round(el.position.h * PX_PER_IN);
      const leftPx = Math.round(el.position.x * PX_PER_IN);
      const topPx = Math.round(el.position.y * PX_PER_IN);
      const { filePath, shadowExtent, hasSignificantShadow } = await renderText(
        el.text,
        el.style,
        widthPx,
        heightPx,
        leftPx,
        topPx
      );
      el.type = 'image';
      el.src = filePath;
      delete el.text;
      delete el.style;
      if (hasSignificantShadow) {
        el.position.x -= shadowExtent.left / PX_PER_IN;
        el.position.y -= shadowExtent.top / PX_PER_IN;
        el.position.w += (shadowExtent.left + shadowExtent.right) / PX_PER_IN;
        el.position.h += (shadowExtent.top + shadowExtent.bottom) / PX_PER_IN;
      }
    } else if (el.type === 'svg') {
      // Render inline SVG as PNG image
      const widthPx = Math.round(el.position.w * PX_PER_IN);
      const heightPx = Math.round(el.position.h * PX_PER_IN);
      const leftPx = Math.round(el.position.x * PX_PER_IN);
      const topPx = Math.round(el.position.y * PX_PER_IN);
      const filePath = await renderSvg(el.svg, widthPx, heightPx, leftPx, topPx);
      el.type = 'image';
      el.src = filePath;
      delete el.svg;
    } else if (el.type === 'gradient') {
      // Render CSS gradient background as PNG image
      const widthPx = Math.round(el.position.w * PX_PER_IN);
      const heightPx = Math.round(el.position.h * PX_PER_IN);
      const leftPx = Math.round(el.position.x * PX_PER_IN);
      const topPx = Math.round(el.position.y * PX_PER_IN);
      const { filePath } = await renderBackground(
        {
          ...(el.style || {}),
          backgroundImage: el.gradient
        },
        widthPx,
        heightPx,
        leftPx,
        topPx
      );
      el.type = 'image';
      el.src = filePath;
      delete el.gradient;
      delete el.style;
    }
  }
}

/**
 * Add all extracted elements (images, text, shapes, tables, lists) to the PowerPoint slide
 */
function addElements(slideData, targetSlide, pres) {
  for (const el of slideData.elements) {
    if (el.type === 'image') {
      let imagePath = el.src.startsWith('file://') ? el.src.replace('file://', '') : el.src;
      targetSlide.addImage({
        path: imagePath,
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h,
        transparency: el.imageProps?.transparency || 0
      });
    } else if (el.type === 'line') {
      targetSlide.addShape(pres.ShapeType.line, {
        x: el.x1,
        y: el.y1,
        w: el.x2 - el.x1,
        h: el.y2 - el.y1,
        line: { color: el.color, width: el.width }
      });
    } else if (el.type === 'shape') {
      const shapeOptions = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h,
        shape: el.shape.rectRadius > 0 ? pres.ShapeType.roundRect : pres.ShapeType.rect
      };

      if (el.shape.fill) {
        shapeOptions.fill = { color: el.shape.fill };
        if (el.shape.transparency != null) shapeOptions.fill.transparency = el.shape.transparency;
      }
      if (el.shape.line) shapeOptions.line = el.shape.line;
      if (el.shape.rectRadius > 0) shapeOptions.rectRadius = el.shape.rectRadius;
      if (el.shape.shadow) shapeOptions.shadow = el.shape.shadow;

      targetSlide.addText(el.text || '', shapeOptions);
    } else if (el.type === 'list') {
      const listOptions = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h,
        fontSize: el.style.fontSize,
        fontFace: el.style.fontFace,
        color: el.style.color,
        align: el.style.align,
        valign: 'top',
        lineSpacing: el.style.lineSpacing,
        paraSpaceBefore: el.style.paraSpaceBefore,
        paraSpaceAfter: el.style.paraSpaceAfter,
        margin: el.style.margin
      };
      if (el.style.margin) listOptions.margin = el.style.margin;
      targetSlide.addText(el.items, listOptions);
    } else if (el.type === 'table') {
      const tableOptions = {
        x: el.position.x,
        y: el.position.y,
        w: el.position.w,
        h: el.position.h
      };
      if (el.colW && el.colW.length) {
        tableOptions.colW = el.colW;
        delete tableOptions.w;
      }
      if (el.rowH && el.rowH.length) {
        tableOptions.rowH = el.rowH;
        delete tableOptions.h;
      }
      targetSlide.addTable(el.rows, tableOptions);
    } else {
      const lineHeight = el.style.lineSpacing || el.style.fontSize * 1.2;
      const isSingleLine = el.position.h <= lineHeight * 1.5;

      let adjustedX = el.position.x;
      let adjustedW = el.position.w;

      // Single-line text needs 2% width compensation for PowerPoint rendering accuracy
      if (isSingleLine) {
        const widthIncrease = el.position.w * 0.02;
        const align = el.style.align;

        if (align === 'center') {
          adjustedX = el.position.x - (widthIncrease / 2);
          adjustedW = el.position.w + widthIncrease;
        } else if (align === 'right') {
          adjustedX = el.position.x - widthIncrease;
          adjustedW = el.position.w + widthIncrease;
        } else {
          adjustedW = el.position.w + widthIncrease;
        }
      }

      const textOptions = {
        x: adjustedX,
        y: el.position.y,
        w: adjustedW,
        h: el.position.h,
        fontSize: el.style.fontSize,
        fontFace: el.style.fontFace,
        color: el.style.color,
        bold: el.style.bold,
        italic: el.style.italic,
        underline: el.style.underline,
        valign: el.style.valign || 'top',
        lineSpacing: el.style.lineSpacing,
        paraSpaceBefore: el.style.paraSpaceBefore,
        paraSpaceAfter: el.style.paraSpaceAfter,
        inset: 0  // Remove default PowerPoint internal padding
      };

      if (el.style.align) textOptions.align = el.style.align;
      if (el.style.margin) textOptions.margin = el.style.margin;
      if (el.style.rotate !== undefined) textOptions.rotate = el.style.rotate;
      if (el.style.transparency !== null && el.style.transparency !== undefined) textOptions.transparency = el.style.transparency;

      targetSlide.addText(el.text, textOptions);
    }
  }
}

/**
 * Extract slide data from HTML page using browser DOM
 * Processes all elements and converts them to PowerPoint-compatible format
 * @returns {Object} { background, elements, placeholders, errors }
 */
async function extractSlideData(page) {
  return await page.evaluate(() => {
    const PT_PER_PX = 0.75;
    const PX_PER_IN = 96;

    // Fonts that are single-weight and should not have bold applied
    // (applying bold causes PowerPoint to use faux bold which makes text wider)
    const SINGLE_WEIGHT_FONTS = ['impact'];

    const shouldSkipBold = (fontFamily) => {
      if (!fontFamily) return false;
      const normalizedFont = fontFamily.toLowerCase().replace(/['"]/g, '').split(',')[0].trim();
      return SINGLE_WEIGHT_FONTS.includes(normalizedFont);
    };

    const pxToInch = (px) => px / PX_PER_IN;
    const pxToPoints = (pxStr) => parseFloat(pxStr) * PT_PER_PX;
    const rgbToHex = (rgbStr) => {
      if (rgbStr === 'rgba(0, 0, 0, 0)' || rgbStr === 'transparent') return 'FFFFFF';

      const match = rgbStr.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (!match) return 'FFFFFF';
      return match.slice(1).map(n => parseInt(n).toString(16).padStart(2, '0')).join('');
    };

    const extractAlpha = (rgbStr) => {
      const match = rgbStr.match(/rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/);
      if (!match || !match[4]) return null;
      const alpha = parseFloat(match[4]);
      return Math.round((1 - alpha) * 100);
    };

    const applyTextTransform = (text, textTransform) => {
      if (textTransform === 'uppercase') return text.toUpperCase();
      if (textTransform === 'lowercase') return text.toLowerCase();
      if (textTransform === 'capitalize') {
        return text.replace(/\b\w/g, c => c.toUpperCase());
      }
      return text;
    };

    // Extract rotation angle from CSS transform and writing-mode
    const getRotation = (transform, writingMode) => {
      let angle = 0;

      // PowerPoint: 90° = text rotated 90° clockwise (reads top to bottom, letters upright)
      // PowerPoint: 270° = text rotated 270° clockwise (reads bottom to top, letters upright)
      if (writingMode === 'vertical-rl') {
        angle = 90;
      } else if (writingMode === 'vertical-lr') {
        angle = 270;
      }

      if (transform && transform !== 'none') {
        const rotateMatch = transform.match(/rotate\((-?\d+(?:\.\d+)?)deg\)/);
        if (rotateMatch) {
          angle += parseFloat(rotateMatch[1]);
        } else {
          const matrixMatch = transform.match(/matrix\(([^)]+)\)/);
          if (matrixMatch) {
            const values = matrixMatch[1].split(',').map(parseFloat);
            // matrix(a, b, c, d, e, f) where rotation = atan2(b, a)
            const matrixAngle = Math.atan2(values[1], values[0]) * (180 / Math.PI);
            angle += Math.round(matrixAngle);
          }
        }
      }

      angle = angle % 360;
      if (angle < 0) angle += 360;

      return angle === 0 ? null : angle;
    };

    /**
     * Calculate element position and size accounting for rotation
     * For 90°/270° rotations, dimensions must be swapped because PowerPoint
     * applies rotation to the original (unrotated) box
     */
    const getPositionAndSize = (el, rect, rotation) => {
      if (rotation === null) {
        return { x: rect.left, y: rect.top, w: rect.width, h: rect.height };
      }

      const isVertical = rotation === 90 || rotation === 270;

      if (isVertical) {
        // Browser shows rotated dimensions (tall box), but PowerPoint needs pre-rotation dimensions (wide box)
        // Swap: browser's height → PPT width, browser's width → PPT height
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        return {
          x: centerX - rect.height / 2,
          y: centerY - rect.width / 2,
          w: rect.height,
          h: rect.width
        };
      }

      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      return {
        x: centerX - el.offsetWidth / 2,
        y: centerY - el.offsetHeight / 2,
        w: el.offsetWidth,
        h: el.offsetHeight
      };
    };

    /**
     * Parse CSS box-shadow into PowerPoint shadow properties
     * Note: PptxGenJS/PowerPoint doesn't support inset shadows - only outer shadows
     */
    const parseBoxShadow = (boxShadow) => {
      if (!boxShadow || boxShadow === 'none') return null;

      const insetMatch = boxShadow.match(/inset/);
      if (insetMatch) return null;

      const colorMatch = boxShadow.match(/rgba?\([^)]+\)/);
      const parts = boxShadow.match(/([-\d.]+)(px|pt)/g);

      if (!parts || parts.length < 2) return null;

      const offsetX = parseFloat(parts[0]);
      const offsetY = parseFloat(parts[1]);
      const blur = parts.length > 2 ? parseFloat(parts[2]) : 0;

      let angle = 0;
      if (offsetX !== 0 || offsetY !== 0) {
        angle = Math.atan2(offsetY, offsetX) * (180 / Math.PI);
        if (angle < 0) angle += 360;
      }

      const offset = Math.sqrt(offsetX * offsetX + offsetY * offsetY) * PT_PER_PX;

      let opacity = 0.5;
      if (colorMatch) {
        const opacityMatch = colorMatch[0].match(/[\d.]+\)$/);
        if (opacityMatch) {
          opacity = parseFloat(opacityMatch[0].replace(')', ''));
        }
      }

      return {
        type: 'outer',
        angle: Math.round(angle),
        blur: blur * 0.75, // Convert to points
        color: colorMatch ? rgbToHex(colorMatch[0]) : '000000',
        offset: offset,
        opacity
      };
    };

    /**
     * Parse inline formatting tags (<b>, <i>, <u>, <strong>, <em>, <span>, etc.) into text runs
     * Flattens nested formatting elements and preserves styling options
     */
    const parseInlineFormatting = (
      element,
      baseOptions = {},
      runs = [],
      baseTextTransform = (x) => x,
      allowBlock = false
    ) => {
      const hasFollowingText = (node) => {
        let next = node.nextSibling;
        while (next) {
          if (next.nodeType === Node.TEXT_NODE && next.textContent.trim()) return true;
          if (next.nodeType === Node.ELEMENT_NODE && next.textContent.trim()) return true;
          next = next.nextSibling;
        }
        return false;
      };
      let prevNodeIsText = false;

      element.childNodes.forEach((node) => {
        let textTransform = baseTextTransform;

        const isText = node.nodeType === Node.TEXT_NODE || node.tagName === 'BR';
        if (isText) {
          const text = node.tagName === 'BR' ? '\n' : textTransform(node.textContent.replace(/\s+/g, ' '));
          const prevRun = runs[runs.length - 1];
          if (prevNodeIsText && prevRun) {
            prevRun.text += text;
          } else {
            runs.push({ text, options: { ...baseOptions } });
          }

        } else if (node.nodeType === Node.ELEMENT_NODE && node.textContent.trim()) {
          const options = { ...baseOptions };
          const computed = window.getComputedStyle(node);

          const isInlineTag = node.tagName === 'SPAN'
            || node.tagName === 'B'
            || node.tagName === 'STRONG'
            || node.tagName === 'I'
            || node.tagName === 'EM'
            || node.tagName === 'U'
            || node.tagName === 'CODE';
          const display = computed.display;
          // Never add line breaks for materialized pseudo-elements
          const isPseudoElement = node.className && (
            node.className.includes('__pseudo_before__') ||
            node.className.includes('__pseudo_after__')
          );
          const allowInlineBreak = allowBlock
            && display
            && !display.startsWith('inline')
            && display !== 'contents'
            && !isPseudoElement;
          const isLayoutContainer = display === 'grid'
            || display === 'inline-grid'
            || display === 'flex'
            || display === 'inline-flex';
          if (isInlineTag) {
            const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;
            if (isBold && !shouldSkipBold(computed.fontFamily)) options.bold = true;
            if (computed.fontStyle === 'italic') options.italic = true;
            if (computed.textDecoration && computed.textDecoration.includes('underline')) options.underline = true;
            if (computed.color && computed.color !== 'rgb(0, 0, 0)') {
              options.color = rgbToHex(computed.color);
              const transparency = extractAlpha(computed.color);
              if (transparency !== null) options.transparency = transparency;
            }
            if (computed.fontSize) options.fontSize = pxToPoints(computed.fontSize);

            if (computed.textTransform && computed.textTransform !== 'none') {
              const transformStr = computed.textTransform;
              textTransform = (text) => applyTextTransform(text, transformStr);
            }

            if (computed.marginLeft && parseFloat(computed.marginLeft) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-left which is not supported in PowerPoint. Remove margin from inline elements.`);
            }
            if (computed.marginRight && parseFloat(computed.marginRight) > 0) {
              errors.push(`Inline element <${node.tagName.toLowerCase()}> has margin-right which is not supported in PowerPoint. Remove margin from inline elements.`);
            }

            const beforeLen = runs.length;
            parseInlineFormatting(node, options, runs, textTransform, allowBlock);
            if (allowInlineBreak && hasFollowingText(node) && runs.length > beforeLen) {
              runs[runs.length - 1].options.breakLine = true;
            }
          } else if (allowBlock) {
            if (isLayoutContainer) return;
            const isBlockLike = computed.display && !computed.display.startsWith('inline') && computed.display !== 'contents';
            const beforeLen = runs.length;
            parseInlineFormatting(node, baseOptions, runs, textTransform, allowBlock);
            const afterLen = runs.length;
            if (isBlockLike && afterLen > beforeLen && hasFollowingText(node)) {
              runs[runs.length - 1].options.breakLine = true;
            }
          }
        }

        prevNodeIsText = isText;
      });

      if (runs.length > 0) {
        runs[0].text = runs[0].text.replace(/^\s+/, '');
        runs[runs.length - 1].text = runs[runs.length - 1].text.replace(/\s+$/, '');
      }

      return runs.filter(r => r.text.length > 0);
    };

    /**
     * Calculate table column widths and row heights from HTML table element
     * Accounts for colspan and normalizes dimensions to match table rect
     */
    const buildTableDimensions = (tableEl, tableRect) => {
      const colWidthsPx = [];
      const rowHeightsPx = [];

      Array.from(tableEl.querySelectorAll('tr')).forEach((row) => {
        const rowRect = row.getBoundingClientRect();
        rowHeightsPx.push(rowRect.height);

        let colIndex = 0;
        Array.from(row.cells).forEach((cell) => {
          const cellRect = cell.getBoundingClientRect();
          const colspan = Number(cell.getAttribute('colspan')) || 1;
          const colWidth = cellRect.width / colspan;
          for (let i = 0; i < colspan; i += 1) {
            const idx = colIndex + i;
            colWidthsPx[idx] = Math.max(colWidthsPx[idx] || 0, colWidth);
          }
          colIndex += colspan;
        });
      });

      const totalColWidth = colWidthsPx.reduce((sum, w) => sum + w, 0);
      const totalRowHeight = rowHeightsPx.reduce((sum, h) => sum + h, 0);
      const colScale = totalColWidth > 0 ? tableRect.width / totalColWidth : 1;
      const rowScale = totalRowHeight > 0 ? tableRect.height / totalRowHeight : 1;

      return {
        colW: colWidthsPx.map((w) => pxToInch(w * colScale)),
        rowH: rowHeightsPx.map((h) => pxToInch(h * rowScale))
      };
    };

    const body = document.body;
    const bodyStyle = window.getComputedStyle(body);
    const bgImage = bodyStyle.backgroundImage;
    const bgColor = bodyStyle.backgroundColor;

    const errors = [];

    let background;
    if (bgImage && bgImage !== 'none') {
      background = {
        type: 'css',
        style: {
          backgroundImage: bgImage,
          backgroundRepeat: bodyStyle.backgroundRepeat,
          backgroundSize: bodyStyle.backgroundSize,
          backgroundPosition: bodyStyle.backgroundPosition,
          backgroundColor: bodyStyle.backgroundColor
        }
      };
    } else {
      background = {
        type: 'color',
        value: rgbToHex(bgColor)
      };
    }

    const elements = [];
    const placeholders = [];
    const textTags = ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI'];
    const processed = new Set();
    const markProcessed = (root) => {
      processed.add(root);
      root.querySelectorAll('*').forEach((child) => processed.add(child));
    };
    const markProcessedList = (root) => {
      processed.add(root);
      root.querySelectorAll('*').forEach((child) => processed.add(child));
    };
    const INLINE_TEXT_TAGS = new Set(['SPAN', 'B', 'STRONG', 'I', 'EM', 'U', 'CODE', 'BR', 'SMALL', 'SUP', 'SUB', 'A']);
    const isLayoutDisplay = (display) => display === 'grid'
      || display === 'inline-grid'
      || display === 'flex'
      || display === 'inline-flex';

    /**
     * Build a PowerPoint text element from an inline HTML element (DIV, SPAN)
     * Handles flex/grid alignment and converts CSS properties to PowerPoint format
     */
    const buildInlineTextElement = (el, rect, computed) => {
      const rotation = getRotation(computed.transform, computed.writingMode);
      const { x, y, w, h } = getPositionAndSize(el, rect, rotation);
      const isFlex = computed.display === 'flex' || computed.display === 'inline-flex';
      const justifyCenter = isFlex && computed.justifyContent === 'center';
      const alignCenter = isFlex && computed.alignItems === 'center';
      const baseStyle = {
        fontSize: pxToPoints(computed.fontSize),
        fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
        fontWeight: computed.fontWeight,
        color: rgbToHex(computed.color),
        align: justifyCenter ? 'center' : (computed.textAlign === 'start' ? 'left' : computed.textAlign),
        lineSpacing: computed.lineHeight && computed.lineHeight !== 'normal' ? pxToPoints(computed.lineHeight) : null,
        paraSpaceBefore: pxToPoints(computed.marginTop),
        paraSpaceAfter: pxToPoints(computed.marginBottom),
        letterSpacing: computed.letterSpacing,
        textShadow: computed.textShadow,
        // PptxGenJS margin array is [left, right, bottom, top]
        margin: [
          pxToPoints(computed.paddingLeft),
          pxToPoints(computed.paddingRight),
          pxToPoints(computed.paddingBottom),
          pxToPoints(computed.paddingTop)
        ],
        valign: alignCenter ? 'middle' : null
      };

      const transparency = extractAlpha(computed.color);
      if (transparency !== null) baseStyle.transparency = transparency;

      if (rotation !== null) baseStyle.rotate = rotation;

      const hasFormatting = el.querySelector('b, i, u, strong, em, span, br, code');
      const transformStr = computed.textTransform;
      if (hasFormatting) {
        const runs = parseInlineFormatting(el, {}, [], (str) => applyTextTransform(str, transformStr), true);
        if (runs.length === 0) return null;
        if (baseStyle.lineSpacing) {
          const maxFontSize = Math.max(
            baseStyle.fontSize,
            ...runs.map(r => r.options?.fontSize || 0)
          );
          if (maxFontSize > baseStyle.fontSize) {
            const lineHeightMultiplier = baseStyle.lineSpacing / baseStyle.fontSize;
            baseStyle.lineSpacing = maxFontSize * lineHeightMultiplier;
          }
        }
        return {
          type: 'div',
          text: runs,
          position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
          style: baseStyle
        };
      }

      const transformedText = applyTextTransform(el.textContent.trim(), transformStr);
      if (!transformedText) return null;
      const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;
      return {
        type: 'div',
        text: transformedText,
        position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
        style: {
          ...baseStyle,
          bold: isBold && !shouldSkipBold(computed.fontFamily),
          italic: computed.fontStyle === 'italic',
          underline: computed.textDecoration.includes('underline')
        }
      };
    };

    // First pass: materialize pseudo-elements as real DOM elements
    document.querySelectorAll('*').forEach((el) => {
      const beforeStyle = window.getComputedStyle(el, '::before');
      const afterStyle = window.getComputedStyle(el, '::after');
      const hasBefore = beforeStyle && beforeStyle.content && beforeStyle.content !== 'none' && beforeStyle.content !== 'normal';
      const hasAfter = afterStyle && afterStyle.content && afterStyle.content !== 'none' && afterStyle.content !== 'normal';

      if (hasBefore) {
        const content = beforeStyle.content.replace(/^["']|["']$/g, '');
        if (content && beforeStyle.display !== 'none') {
          const span = document.createElement('span');
          span.className = '__pseudo_before__';
          span.textContent = content;

          // Preserve original positioning to maintain layout
          // Key: preserve position:absolute to keep element out of document flow
          span.style.cssText = `
            display: ${beforeStyle.display};
            position: ${beforeStyle.position};
            left: ${beforeStyle.left};
            right: ${beforeStyle.right};
            top: ${beforeStyle.top};
            bottom: ${beforeStyle.bottom};
            font-size: ${beforeStyle.fontSize};
            font-family: ${beforeStyle.fontFamily};
            font-weight: ${beforeStyle.fontWeight};
            font-style: ${beforeStyle.fontStyle};
            color: ${beforeStyle.color};
            text-decoration: ${beforeStyle.textDecoration};
            line-height: ${beforeStyle.lineHeight};
          `;
          el.insertBefore(span, el.firstChild);
        }
      }

      if (hasAfter) {
        const content = afterStyle.content.replace(/^["']|["']$/g, '');
        if (content && afterStyle.display !== 'none') {
          const span = document.createElement('span');
          span.className = '__pseudo_after__';
          span.textContent = content;

          // Preserve original positioning to maintain layout
          span.style.cssText = `
            display: ${afterStyle.display};
            position: ${afterStyle.position};
            left: ${afterStyle.left};
            right: ${afterStyle.right};
            top: ${afterStyle.top};
            bottom: ${afterStyle.bottom};
            font-size: ${afterStyle.fontSize};
            font-family: ${afterStyle.fontFamily};
            font-weight: ${afterStyle.fontWeight};
            font-style: ${afterStyle.fontStyle};
            color: ${afterStyle.color};
            text-decoration: ${afterStyle.textDecoration};
            line-height: ${afterStyle.lineHeight};
          `;
          el.appendChild(span);
        }
      }
    });

    /**
     * Main extraction loop: Process all DOM elements and convert to PowerPoint format
     * Elements are processed in order: placeholders, images, SVG, tables, lists, text, shapes
     * Uses 'processed' set to track already-handled elements and avoid duplication
     */
    document.querySelectorAll('*').forEach((el) => {
      if (processed.has(el)) return;

      // Validate text elements don't have backgrounds, borders, or shadows
      if (textTags.includes(el.tagName)) {
        const computed = window.getComputedStyle(el);
        const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';
        const hasBgImage = computed.backgroundImage && computed.backgroundImage !== 'none';
        const hasBorder = (computed.borderWidth && parseFloat(computed.borderWidth) > 0) ||
          (computed.borderTopWidth && parseFloat(computed.borderTopWidth) > 0) ||
          (computed.borderRightWidth && parseFloat(computed.borderRightWidth) > 0) ||
          (computed.borderBottomWidth && parseFloat(computed.borderBottomWidth) > 0) ||
          (computed.borderLeftWidth && parseFloat(computed.borderLeftWidth) > 0);
        const hasShadow = computed.boxShadow && computed.boxShadow !== 'none';

        if (hasBg || hasBgImage || hasBorder || hasShadow) {
          errors.push(
            `Text element <${el.tagName.toLowerCase()}> has ${hasBg || hasBgImage ? 'background' : hasBorder ? 'border' : 'shadow'}. ` +
            'Backgrounds, borders, and shadows are only supported on <div> elements, not text elements.'
          );
          return;
        }
      }

      if (el.className && el.className.includes('placeholder') && el.tagName !== 'TABLE') {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
          errors.push(
            `Placeholder "${el.id || 'unnamed'}" has ${rect.width === 0 ? 'width: 0' : 'height: 0'}. Check the layout CSS.`
          );
        } else {
          placeholders.push({
            id: el.id || `placeholder-${placeholders.length}`,
            x: pxToInch(rect.left),
            y: pxToInch(rect.top),
            w: pxToInch(rect.width),
            h: pxToInch(rect.height)
          });
        }
        processed.add(el);
        return;
      }

      if (el.tagName === 'IMG') {
        const computed = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          elements.push({
            type: 'image',
            src: el.src,
            position: {
              x: pxToInch(rect.left),
              y: pxToInch(rect.top),
              w: pxToInch(rect.width),
              h: pxToInch(rect.height)
            },
            style: {
              objectFit: computed.objectFit,
              objectPosition: computed.objectPosition,
              borderRadius: computed.borderRadius,
              filter: computed.filter,
              boxShadow: computed.boxShadow
            },
            imageProps: {
              transparency: computed.opacity ? Math.round((1 - parseFloat(computed.opacity)) * 100) : 0
            }
          });
          processed.add(el);
          return;
        }
      }

      if (el.tagName === 'SVG') {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          const serializer = new XMLSerializer();
          const svgMarkup = serializer.serializeToString(el);
          elements.push({
            type: 'svg',
            svg: svgMarkup,
            position: {
              x: pxToInch(rect.left),
              y: pxToInch(rect.top),
              w: pxToInch(rect.width),
              h: pxToInch(rect.height)
            }
          });
          markProcessed(el);
          return;
        }
      }

      if (el.tagName === 'SPAN') {
        const parent = el.parentElement;
        if (parent) {
          const parentDisplay = window.getComputedStyle(parent).display;
          if (isLayoutDisplay(parentDisplay)) {
            const textAncestor = el.closest('p,h1,h2,h3,h4,h5,h6,li,ul,ol');
            if (textAncestor) return;
            const rect = el.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0 && el.textContent.trim()) {
              const computed = window.getComputedStyle(el);
              const textElement = buildInlineTextElement(el, rect, computed);
              if (textElement) elements.push(textElement);
              processed.add(el);
              return;
            }
          }
        }
      }

      if (el.tagName === 'TABLE') {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
          markProcessed(el);
          return;
        }

        const rows = [];

        Array.from(el.querySelectorAll('tr')).forEach((row) => {
          const cells = [];
          Array.from(row.cells).forEach((cell) => {
            const computed = window.getComputedStyle(cell);
            const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;
            const textTransform = computed.textTransform;
            const hasFormatting = cell.querySelector('b, i, u, strong, em, span, br');
            const cellText = hasFormatting
              ? parseInlineFormatting(cell, {}, [], (str) => applyTextTransform(str, textTransform), true)
              : applyTextTransform(cell.innerText || '', textTransform);

            const cellOptions = {
              fontSize: pxToPoints(computed.fontSize),
              fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
              color: rgbToHex(computed.color),
              bold: isBold && !shouldSkipBold(computed.fontFamily),
              italic: computed.fontStyle === 'italic',
              underline: computed.textDecoration.includes('underline'),
              colspan: Number(cell.getAttribute('colspan')) || null,
              rowspan: Number(cell.getAttribute('rowspan')) || null
            };

            const textTransparency = extractAlpha(computed.color);
            if (textTransparency !== null) cellOptions.transparency = textTransparency;

            const align = computed.textAlign === 'start' ? 'left' : computed.textAlign === 'end' ? 'right' : computed.textAlign;
            if (['left', 'center', 'right', 'justify'].includes(align)) cellOptions.align = align;

            const valign = computed.verticalAlign;
            if (['top', 'middle', 'bottom'].includes(valign)) cellOptions.valign = valign;

            if (computed.lineHeight && computed.lineHeight !== 'normal') {
              cellOptions.lineSpacing = pxToPoints(computed.lineHeight);
            }

            const paddingTop = pxToPoints(computed.paddingTop);
            const paddingRight = pxToPoints(computed.paddingRight);
            const paddingBottom = pxToPoints(computed.paddingBottom);
            const paddingLeft = pxToPoints(computed.paddingLeft);
            if (paddingTop || paddingRight || paddingBottom || paddingLeft) {
              cellOptions.margin = [paddingTop, paddingRight, paddingBottom, paddingLeft];
            }

            const bgColor = rgbToHex(computed.backgroundColor);
            const bgTransparency = extractAlpha(computed.backgroundColor);
            if (bgColor) {
              cellOptions.fill = { color: bgColor };
              if (bgTransparency !== null) cellOptions.fill.transparency = bgTransparency;
            }

            const borderTop = pxToPoints(computed.borderTopWidth);
            const borderRight = pxToPoints(computed.borderRightWidth);
            const borderBottom = pxToPoints(computed.borderBottomWidth);
            const borderLeft = pxToPoints(computed.borderLeftWidth);
            if (borderTop || borderRight || borderBottom || borderLeft) {
              cellOptions.border = [
                borderTop ? { pt: borderTop, color: rgbToHex(computed.borderTopColor) } : null,
                borderRight ? { pt: borderRight, color: rgbToHex(computed.borderRightColor) } : null,
                borderBottom ? { pt: borderBottom, color: rgbToHex(computed.borderBottomColor) } : null,
                borderLeft ? { pt: borderLeft, color: rgbToHex(computed.borderLeftColor) } : null
              ];
            }

            cells.push({ text: cellText, options: cellOptions });
          });
          rows.push(cells);
        });

        const hasCells = rows.some((row) => row.length > 0);
        if (!hasCells) {
          errors.push(`Table "${el.id || 'unnamed'}" has no cells. Check the HTML structure.`);
          markProcessed(el);
          return;
        }

        const { colW, rowH } = buildTableDimensions(el, rect);

        elements.push({
          type: 'table',
          rows,
          position: {
            x: pxToInch(rect.left),
            y: pxToInch(rect.top),
            w: pxToInch(rect.width),
            h: pxToInch(rect.height)
          },
          colW,
          rowH
        });

        markProcessed(el);
        return;
      }

      if (el.tagName === 'DIV') {
        // Allow DIVs inside LI (may be part of complex lists like checklist cards)
        const textAncestor = el.closest('p,h1,h2,h3,h4,h5,h6');
        if (textAncestor) return;

        const computed = window.getComputedStyle(el);
        const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';
        const bgImage = computed.backgroundImage;
        const hasBgImage = bgImage && bgImage !== 'none';
        const hasBorder = (computed.borderWidth && parseFloat(computed.borderWidth) > 0) ||
          (computed.borderTopWidth && parseFloat(computed.borderTopWidth) > 0) ||
          (computed.borderRightWidth && parseFloat(computed.borderRightWidth) > 0) ||
          (computed.borderBottomWidth && parseFloat(computed.borderBottomWidth) > 0) ||
          (computed.borderLeftWidth && parseFloat(computed.borderLeftWidth) > 0);
        const hasShadow = computed.boxShadow && computed.boxShadow !== 'none';
        const hasOnlyInlineChildren = Array.from(el.children)
          .every((child) => INLINE_TEXT_TAGS.has(child.tagName));
        const hasText = el.textContent && el.textContent.trim();

        const isLayoutContainer = isLayoutDisplay(computed.display);
        if (!hasBg && !hasBgImage && !hasBorder && !hasShadow && hasOnlyInlineChildren && hasText && !isLayoutContainer) {
          const rect = el.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            const textElement = buildInlineTextElement(el, rect, computed);
            if (textElement) elements.push(textElement);
            markProcessed(el);
            return;
          }
        }
      }

      const isContainer = el.tagName === 'DIV' && !textTags.includes(el.tagName);
      if (isContainer) {
        const computed = window.getComputedStyle(el);
        const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';

        for (const node of el.childNodes) {
          if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent.trim();
            if (text) {
              errors.push(
                `DIV element contains unwrapped text "${text.substring(0, 50)}${text.length > 50 ? '...' : ''}". ` +
                'All text must be wrapped in <p>, <h1>-<h6>, <ul>, or <ol> tags to appear in PowerPoint.'
              );
            }
          }
        }

        const bgImage = computed.backgroundImage;
        const hasBgImage = bgImage && bgImage !== 'none';

        const borderTop = computed.borderTopWidth;
        const borderRight = computed.borderRightWidth;
        const borderBottom = computed.borderBottomWidth;
        const borderLeft = computed.borderLeftWidth;
        const borders = [borderTop, borderRight, borderBottom, borderLeft].map(b => parseFloat(b) || 0);
        const hasBorder = borders.some(b => b > 0);
        const hasUniformBorder = hasBorder && borders.every(b => b === borders[0]);
        const borderLines = [];
        // Non-uniform borders or borders with background images must be rendered as separate line elements
        const useBorderLines = hasBorder && (hasBgImage || !hasUniformBorder);
        if (useBorderLines) {
          const rect = el.getBoundingClientRect();
          const actualWidth = el.offsetWidth || rect.width;
          const actualHeight = el.offsetHeight || rect.height;
          const x = pxToInch(rect.left);
          const y = pxToInch(rect.top);
          const w = pxToInch(actualWidth);
          const h = pxToInch(actualHeight);

          // Create border lines with inset positioning (half line width) to center on edge
          if (parseFloat(borderTop) > 0) {
            const widthPt = pxToPoints(borderTop);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x, y1: y + inset, x2: x + w, y2: y + inset,
              width: widthPt,
              color: rgbToHex(computed.borderTopColor)
            });
          }
          if (parseFloat(borderRight) > 0) {
            const widthPt = pxToPoints(borderRight);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x + w - inset, y1: y, x2: x + w - inset, y2: y + h,
              width: widthPt,
              color: rgbToHex(computed.borderRightColor)
            });
          }
          if (parseFloat(borderBottom) > 0) {
            const widthPt = pxToPoints(borderBottom);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x, y1: y + h - inset, x2: x + w, y2: y + h - inset,
              width: widthPt,
              color: rgbToHex(computed.borderBottomColor)
            });
          }
          if (parseFloat(borderLeft) > 0) {
            const widthPt = pxToPoints(borderLeft);
            const inset = (widthPt / 72) / 2;
            borderLines.push({
              type: 'line',
              x1: x + inset, y1: y, x2: x + inset, y2: y + h,
              width: widthPt,
              color: rgbToHex(computed.borderLeftColor)
            });
          }
        }

        if (hasBg || hasBorder || hasBgImage) {
          const rect = el.getBoundingClientRect();
          if (rect.width > 0 && rect.height > 0) {
            const shadow = parseBoxShadow(computed.boxShadow);

            const actualWidth = rect.width;
            const actualHeight = rect.height;

            if (!hasBgImage && (hasBg || hasUniformBorder)) {
              elements.push({
                type: 'shape',
                text: '',  // Shape only - child text elements render on top
                position: {
                  x: pxToInch(rect.left),
                  y: pxToInch(rect.top),
                  w: pxToInch(actualWidth),
                  h: pxToInch(actualHeight)
                },
                shape: {
                  fill: hasBg ? rgbToHex(computed.backgroundColor) : null,
                  transparency: hasBg ? extractAlpha(computed.backgroundColor) : null,
                  line: hasUniformBorder && !hasBgImage ? {
                    color: rgbToHex(computed.borderColor),
                    width: pxToPoints(computed.borderWidth)
                  } : null,
                  // Convert border-radius: 50%+ = circle, <50% = % of min dimension, px/pt = convert to inches
                  rectRadius: (() => {
                    const radius = computed.borderRadius;
                    const radiusValue = parseFloat(radius);
                    if (radiusValue === 0) return 0;

                    if (radius.includes('%')) {
                      if (radiusValue >= 50) return 1;
                      const minDim = Math.min(actualWidth, actualHeight);
                      return (radiusValue / 100) * pxToInch(minDim);
                    }

                    if (radius.includes('pt')) return radiusValue / 72;
                    return radiusValue / PX_PER_IN;
                  })(),
                  shadow: shadow
                }
              });
            }

            if (hasBgImage) {
              elements.push({
                type: 'bgImage',
                position: {
                  x: pxToInch(rect.left),
                  y: pxToInch(rect.top),
                  w: pxToInch(actualWidth),
                  h: pxToInch(actualHeight)
                },
                style: {
                  backgroundImage: bgImage,
                  backgroundRepeat: computed.backgroundRepeat,
                  backgroundSize: computed.backgroundSize,
                  backgroundPosition: computed.backgroundPosition,
                  backgroundColor: computed.backgroundColor,
                  borderRadius: computed.borderRadius,
                  boxShadow: computed.boxShadow
                }
              });
            }

            elements.push(...borderLines);

            const hasOnlyInlineChildren = Array.from(el.children)
              .every((child) => INLINE_TEXT_TAGS.has(child.tagName));
            const hasText = el.textContent && el.textContent.trim();
            if (hasOnlyInlineChildren && hasText) {
              const textElement = buildInlineTextElement(el, rect, computed);
              if (textElement) elements.push(textElement);
              markProcessed(el);
              return;
            }

            processed.add(el);
            return;
          }
        }
      }

      if (el.tagName === 'UL' || el.tagName === 'OL') {
        const ulComputed = window.getComputedStyle(el);
        if (isLayoutDisplay(ulComputed.display)) {
          processed.add(el);
          return;
        }
        const liElements = Array.from(el.children).filter((child) => child.tagName === 'LI');
        const hasLayoutLi = liElements.some((li) => isLayoutDisplay(window.getComputedStyle(li).display));
        if (hasLayoutLi) {
          processed.add(el);
          return;
        }

        // Complex styled lists (e.g., checklists with cards/borders) should be extracted as individual shapes
        const firstLiForCheck = liElements[0];
        const firstLiStyle = firstLiForCheck ? window.getComputedStyle(firstLiForCheck) : null;
        const listStyleForCheck = firstLiStyle ? (firstLiStyle.listStyleType || ulComputed.listStyleType) : ulComputed.listStyleType;
        const isChecklistClass = el.className && (
          el.className.includes('checklist') ||
          el.className.includes('check-list') ||
          el.className.includes('task-list')
        );
        const isStyledList = listStyleForCheck === 'none' || isChecklistClass;

        if (isStyledList) {
          const hasComplexLayout = liElements.some((li) => {
            const divs = li.querySelectorAll('div');
            return Array.from(divs).some((div) => {
              const computed = window.getComputedStyle(div);
              const hasBg = computed.backgroundColor && computed.backgroundColor !== 'rgba(0, 0, 0, 0)';
              const hasBorder = parseFloat(computed.borderWidth) > 0 ||
                               parseFloat(computed.borderTopWidth) > 0 ||
                               parseFloat(computed.borderRightWidth) > 0 ||
                               parseFloat(computed.borderBottomWidth) > 0 ||
                               parseFloat(computed.borderLeftWidth) > 0;
              const isLayout = isLayoutDisplay(computed.display);
              return hasBg || hasBorder || isLayout;
            });
          });

          if (hasComplexLayout) {
            processed.add(el);
            return;
          }
        }
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const items = [];
        const ulPaddingLeftPt = pxToPoints(ulComputed.paddingLeft);

        const firstLi = liElements[0] || el;
        const liComputed = window.getComputedStyle(firstLi);
        const listStyleType = liComputed.listStyleType || ulComputed.listStyleType;

        const hasPseudoBullet = firstLi.querySelector('.__pseudo_before__') !== null;
        const useBullet = listStyleType !== 'none' || hasPseudoBullet;

        const liPaddingLeftPt = pxToPoints(liComputed.paddingLeft);
        const liPaddingRightPt = pxToPoints(liComputed.paddingRight);
        const liPaddingTopPt = pxToPoints(liComputed.paddingTop);
        const liPaddingBottomPt = pxToPoints(liComputed.paddingBottom);

        // Check if LI has absolute-positioned pseudo-elements at left:0
        // If so, padding-left is for the pseudo-element space, not text margin
        let hasAbsolutePseudoAtLeftZero = false;
        const pseudoElements = firstLi.querySelectorAll('.__pseudo_before__, .__pseudo_after__');
        if (pseudoElements.length > 0) {
          const beforeStyle = window.getComputedStyle(firstLi, '::before');
          const afterStyle = window.getComputedStyle(firstLi, '::after');

          const checkPseudo = (style) => {
            if (!style || !style.content || style.content === 'none') return false;
            return style.position === 'absolute' &&
                   (style.left === '0px' || style.left === '0');
          };

          hasAbsolutePseudoAtLeftZero = checkPseudo(beforeStyle) || checkPseudo(afterStyle);
        }

        // Determine text margin: if pseudo-element at left:0, padding-left is for pseudo (margin=0)
        // Otherwise, use LI's padding as margin
        let textMargin;
        if (hasAbsolutePseudoAtLeftZero) {
          textMargin = [0, liPaddingRightPt, liPaddingBottomPt, liPaddingTopPt];
        } else {
          textMargin = [liPaddingLeftPt, liPaddingRightPt, liPaddingBottomPt, liPaddingTopPt];
        }

        const textIndent = useBullet ? ulPaddingLeftPt : 0;

        const bullet_code_map = { 1: "2022", 2: "25E6", 3: "25AA" };

        /**
         * Extract text with formatting from any element, including layout containers
         * Used as fallback when parseInlineFormatting fails
         */
        const extractTextFromAnyElement = (element) => {
          const runs = [];

          const walkNode = (node) => {
            if (node.nodeType === Node.TEXT_NODE) {
              const text = node.textContent.replace(/\s+/g, ' ');
              if (text) {
                runs.push({ text, options: {} });
              }
            } else if (node.nodeType === Node.ELEMENT_NODE) {
              const computed = window.getComputedStyle(node);
              const tagName = node.tagName;

              if (tagName === 'UL' || tagName === 'OL') return;

              const options = {};
              const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;
              if (isBold) options.bold = true;
              if (computed.fontStyle === 'italic') options.italic = true;
              if (computed.textDecoration && computed.textDecoration.includes('underline')) options.underline = true;
              if (computed.color && computed.color !== 'rgb(0, 0, 0)') {
                options.color = rgbToHex(computed.color);
              }
              if (computed.fontSize) {
                options.fontSize = pxToPoints(computed.fontSize);
              }

              const beforeLen = runs.length;
              node.childNodes.forEach(child => walkNode(child));

              if (Object.keys(options).length > 0) {
                for (let i = beforeLen; i < runs.length; i++) {
                  runs[i].options = { ...options, ...runs[i].options };
                }
              }
            }
          };

          walkNode(element);

          const merged = [];
          for (const run of runs) {
            const last = merged[merged.length - 1];
            if (last && JSON.stringify(last.options) === JSON.stringify(run.options)) {
              last.text += run.text;
            } else {
              merged.push(run);
            }
          }

          return merged.map(r => ({ ...r, text: r.text.trim() })).filter(r => r.text);
        };

        /**
         * Extract Unicode code point from a character (for bullet symbols)
         */
        const getUnicodeCode = (char) => {
          if (!char || char.length === 0) return null;
          return char.codePointAt(0).toString(16).toUpperCase();
        };

        /**
         * Extract text runs from a list item, handling nested lists and pseudo-element bullets
         */
        const extractLiOwnRuns = (liEl, level) => {
          const clone = liEl.cloneNode(true);
          clone.querySelectorAll('ul,ol').forEach((n) => n.remove());

          const holder = document.createElement('div');
          holder.style.position = 'fixed';
          holder.style.left = '-100000px';
          holder.style.top = '0';
          holder.style.visibility = 'hidden';
          holder.style.pointerEvents = 'none';
          holder.appendChild(clone);
          document.body.appendChild(holder);

          const pseudoBefore = clone.querySelector('.__pseudo_before__');
          let customBulletCode = null;

          if (pseudoBefore) {
            const bulletText = pseudoBefore.textContent;
            if (bulletText) {
              const firstChar = bulletText.trim()[0];
              if (firstChar && /[•\-\*▪▸○●◆◇■□✓✗➤➢→←↑↓◀▶▲▼✔✖]/.test(firstChar)) {
                customBulletCode = getUnicodeCode(firstChar);
                pseudoBefore.remove();
              }
            }
          }

          let runs = parseInlineFormatting(clone, { breakLine: false }, [], (x) => x, true);

          if (runs.length === 0 && clone.textContent.trim()) {
            runs = extractTextFromAnyElement(clone);
          }

          document.body.removeChild(holder);

          if (runs.length > 0) {
            runs[0].text = runs[0].text.replace(/^[•\-\*▪▸○●◆◇■□✓✗➤➢→←↑↓◀▶▲▼✔✖]\s*/, '');
            runs[0].text = runs[0].text.replace(/^\s+/, '');
          }

          const nonEmpty = runs.filter(r => r && typeof r.text === 'string' && r.text.trim().length > 0);
          if (nonEmpty.length === 0) return [];

          if (useBullet) {
            nonEmpty[0].options = nonEmpty[0].options || {};
            const bulletCode = customBulletCode || bullet_code_map[level % 3 + 1];
            nonEmpty[0].options.bullet = { "indent": textIndent, "code": bulletCode };
            nonEmpty[0].options.indentLevel = level;
          }

          return nonEmpty;
        };

        /**
         * Recursively walk list structure and extract text runs with proper indentation
         */
        const walkList = (listEl, level) => {
          const lis = Array.from(listEl.children).filter((c) => c.tagName === 'LI');
          lis.forEach((li, idx) => {
            const ownRuns = extractLiOwnRuns(li, level);
            if (ownRuns.length > 0) {
              const hasSiblingAfter = idx < lis.length - 1;
              const nested = li.querySelector(':scope > ul, :scope > ol');
              const hasNested = !!nested;

              if (hasSiblingAfter || hasNested) {
                ownRuns[ownRuns.length - 1].options = ownRuns[ownRuns.length - 1].options || {};
                ownRuns[ownRuns.length - 1].options.breakLine = true;
              }
              items.push(...ownRuns);
            }

            const nested = li.querySelector(':scope > ul, :scope > ol');
            if (nested) {
              walkList(nested, level + 1);
              if (idx < lis.length - 1 && items.length > 0) {
                const last = items[items.length - 1];
                last.options = last.options || {};
                last.options.breakLine = true;
              }
            }
          });
        };

        walkList(el, 0);

        const computed = window.getComputedStyle(liElements[0] || el);

        let lineSpacing = null;
        if (computed.lineHeight && computed.lineHeight !== 'normal') {
          lineSpacing = pxToPoints(computed.lineHeight);
        }

        elements.push({
          type: 'list',
          items: items,
          position: {
            x: pxToInch(rect.left),
            y: pxToInch(rect.top),
            w: pxToInch(rect.width),
            h: pxToInch(rect.height)  // Use rect.height directly - matches html2pptx_old.js
          },
          style: {
            fontSize: pxToPoints(computed.fontSize),
            fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
            color: rgbToHex(computed.color),
            transparency: extractAlpha(computed.color),
            align: computed.textAlign === 'start' ? 'left' : computed.textAlign,
            lineSpacing: lineSpacing,
            paraSpaceBefore: 0,
            paraSpaceAfter: pxToPoints(computed.marginBottom),
            // PptxGenJS margin format: [left, right, bottom, top]
            margin: textMargin
          }
        });

        markProcessedList(el);
        return;
      }

      if (!textTags.includes(el.tagName)) return;

      const textParent = el.parentElement?.closest('p,h1,h2,h3,h4,h5,h6');
      if (textParent) return;

      if (el.tagName === 'LI' && el.querySelector('p,h1,h2,h3,h4,h5,h6,div,ul,ol')) return;

      const rect = el.getBoundingClientRect();
      const text = el.textContent.trim();
      if (rect.width === 0 || rect.height === 0 || !text) return;

      if (el.tagName !== 'LI' && /^[•\-\*▪▸○●◆◇■□]\s/.test(text.trimStart())) {
        errors.push(
          `Text element <${el.tagName.toLowerCase()}> starts with bullet symbol "${text.substring(0, 20)}...". ` +
          'Use <ul> or <ol> lists instead of manual bullet symbols.'
        );
        return;
      }

      const computed = window.getComputedStyle(el);
      const rotation = getRotation(computed.transform, computed.writingMode);
      const { x, y, w, h } = getPositionAndSize(el, rect, rotation);

      const baseStyle = {
        fontSize: pxToPoints(computed.fontSize),
        fontFace: computed.fontFamily.split(',')[0].replace(/['"]/g, '').trim(),
        fontWeight: computed.fontWeight,
        color: rgbToHex(computed.color),
        align: computed.textAlign === 'start' ? 'left' : computed.textAlign,
        lineSpacing: pxToPoints(computed.lineHeight),
        paraSpaceBefore: pxToPoints(computed.marginTop),
        paraSpaceAfter: pxToPoints(computed.marginBottom),
        letterSpacing: computed.letterSpacing,
        textShadow: computed.textShadow,
        // PptxGenJS margin format: [left, right, bottom, top]
        margin: [
          pxToPoints(computed.paddingLeft),
          pxToPoints(computed.paddingRight),
          pxToPoints(computed.paddingBottom),
          pxToPoints(computed.paddingTop)
        ]
      };

      const transparency = extractAlpha(computed.color);
      if (transparency !== null) baseStyle.transparency = transparency;

      if (rotation !== null) baseStyle.rotate = rotation;

      const hasFormatting = el.querySelector('b, i, u, strong, em, span, br');

      if (hasFormatting) {
        const transformStr = computed.textTransform;
        const runs = parseInlineFormatting(el, {}, [], (str) => applyTextTransform(str, transformStr), false);

        const adjustedStyle = { ...baseStyle };
        if (adjustedStyle.lineSpacing) {
          const maxFontSize = Math.max(
            adjustedStyle.fontSize,
            ...runs.map(r => r.options?.fontSize || 0)
          );
          if (maxFontSize > adjustedStyle.fontSize) {
            const lineHeightMultiplier = adjustedStyle.lineSpacing / adjustedStyle.fontSize;
            adjustedStyle.lineSpacing = maxFontSize * lineHeightMultiplier;
          }
        }

        elements.push({
          type: el.tagName.toLowerCase(),
          text: runs,
          position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
          style: adjustedStyle
        });
      } else {
        const textTransform = computed.textTransform;
        const transformedText = applyTextTransform(text, textTransform);

        const isBold = computed.fontWeight === 'bold' || parseInt(computed.fontWeight) >= 600;

        elements.push({
          type: el.tagName.toLowerCase(),
          text: transformedText,
          position: { x: pxToInch(x), y: pxToInch(y), w: pxToInch(w), h: pxToInch(h) },
          style: {
            ...baseStyle,
            bold: isBold && !shouldSkipBold(computed.fontFamily),
            italic: computed.fontStyle === 'italic',
            underline: computed.textDecoration.includes('underline')
          }
        });
      }

      processed.add(el);
    });

    return { background, elements, placeholders, errors };
  });
}

/**
 * Main function: Convert HTML file to PowerPoint slide
 * @param {string} htmlFile - Path to HTML file
 * @param {Object} pres - PptxGenJS presentation instance
 * @param {Object} options - Optional configuration { slide, tmpDir }
 * @returns {Promise<{slide, placeholders}>} Slide object and array of placeholder positions
 */
async function html2pptx(htmlFile, pres, options = {}) {
  const { slide = null } = options;
  const tmpDir = options.tmpDir || fs.mkdtempSync(path.join(os.tmpdir(), 'html2pptx-'));

  try {
    const launchOptions = { env: { TMPDIR: tmpDir } };
    if (process.platform === 'darwin') {
      launchOptions.channel = 'chrome';
    }

    const browser = await chromium.launch(launchOptions);

    let bodyDimensions;
    let slideData;

    const filePath = path.isAbsolute(htmlFile) ? htmlFile : path.join(process.cwd(), htmlFile);
    const validationErrors = [];

    try {
      const page = await browser.newPage();
      page.on('console', (msg) => {
        console.log(`Browser console: ${msg.text()}`);
      });

      await page.goto(`file://${filePath}`);

      bodyDimensions = await getBodyDimensions(page);

      await page.setViewportSize({
        width: Math.round(bodyDimensions.width),
        height: Math.round(bodyDimensions.height)
      });

      slideData = await extractSlideData(page);
      await rasterizeGradients(page, slideData, bodyDimensions, tmpDir);
    } finally {
      await browser.close();
    }

    const resolveImagePath = (src) => {
      if (!src || typeof src !== 'string') return null;
      if (src.startsWith('data:')) return null;
      if (src.startsWith('http://') || src.startsWith('https://')) return null;
      if (src.startsWith('file://')) return src.replace('file://', '');
      if (path.isAbsolute(src)) return src;
      return path.join(path.dirname(filePath), src);
    };

    if (bodyDimensions.errors && bodyDimensions.errors.length > 0) {
      validationErrors.push(...bodyDimensions.errors);
    }

    const dimensionErrors = validateDimensions(bodyDimensions, pres);
    if (dimensionErrors.length > 0) {
      validationErrors.push(...dimensionErrors);
    }

    const textBoxPositionErrors = validateTextBoxPosition(slideData, bodyDimensions);
    if (textBoxPositionErrors.length > 0) {
      validationErrors.push(...textBoxPositionErrors);
    }

    if (slideData.errors && slideData.errors.length > 0) {
      validationErrors.push(...slideData.errors);
    }

    const backgroundPath = slideData.background?.type === 'image'
      ? resolveImagePath(slideData.background.path)
      : null;
    if (backgroundPath && !fs.existsSync(backgroundPath)) {
      validationErrors.push(`Background image not found: ${backgroundPath}`);
    }

    for (const el of slideData.elements) {
      if (el.type !== 'image') continue;
      const imagePath = resolveImagePath(el.src);
      if (imagePath && !fs.existsSync(imagePath)) {
        validationErrors.push(`Image not found: ${imagePath}`);
      }
    }

    if (validationErrors.length > 0) {
      const errorMessage = validationErrors.length === 1
        ? validationErrors[0]
        : `Multiple validation errors found:\n${validationErrors.map((e, i) => `  ${i + 1}. ${e}`).join('\n')}`;
      throw new Error(errorMessage);
    }

    const targetSlide = slide || pres.addSlide();

    await addBackground(slideData, targetSlide, tmpDir);
    addElements(slideData, targetSlide, pres);

    return { slide: targetSlide, placeholders: slideData.placeholders };
  } catch (error) {
    if (!error.message.startsWith(htmlFile)) {
      throw new Error(`${htmlFile}: ${error.message}`);
    }
    throw error;
  }
}

module.exports = html2pptx;
