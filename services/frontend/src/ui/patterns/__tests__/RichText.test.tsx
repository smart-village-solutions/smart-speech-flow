import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RichText } from '@/ui/patterns/RichText';
import { plainHttp } from '@/test/plainHttp';

function rendered(html: string, inline = false): HTMLElement {
  const { container } = render(
    <div>
      <RichText html={html} inline={inline} />
    </div>
  );
  return container.firstElementChild as HTMLElement;
}

describe('RichText', () => {
  it('rebuilds paragraphs, emphasis and line breaks', () => {
    const host = rendered('<p><strong>Bold</strong> and <em>em</em><br>next</p>');

    expect(host.innerHTML).toBe('<p><strong>Bold</strong> and <em>em</em><br>next</p>');
  });

  it('drops empty blocks, as the live login description ends in one', () => {
    const host = rendered(
      '<p>Bitte wählen Sie.</p><p></p><p> </p><p><br></p><p><strong></strong></p>'
    );

    expect(host.innerHTML).toBe('<p>Bitte wählen Sie.</p>');
  });

  it('renders lists without empty items', () => {
    const host = rendered('<ul><li>One</li><li></li></ul><ol><li>Two</li></ol><ul><li> </li></ul>');

    expect(host.querySelectorAll('li')).toHaveLength(2);
    expect(host.querySelectorAll('ul')).toHaveLength(1);
    expect(host.querySelector('ul')).toHaveClass('list-disc');
    expect(host.querySelector('ol')).toHaveClass('list-decimal');
  });

  it('opens https and mailto links in a new tab without an opener', () => {
    const host = rendered(
      '<p><a href="https://www.kassel.de/impressum.php">Impressum</a> <a href="mailto:dialog@kassel.de">Mail</a></p>'
    );
    const links = [...host.querySelectorAll('a')];

    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      'https://www.kassel.de/impressum.php',
      'mailto:dialog@kassel.de',
    ]);
    for (const link of links) {
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }
  });

  it('unwraps elements outside the allowlist to their text', () => {
    const host = rendered('<div><p><span>Kept</span> <b>text</b></p></div><h1>Heading</h1>');

    expect(host.innerHTML).toBe('<p>Kept text</p><p>Heading</p>');
  });

  it('puts text outside any block into a paragraph, as the gateway unwraps div and h2', () => {
    expect(rendered('Wählen Sie <strong>Ihre</strong> Organisation.').innerHTML).toBe(
      '<p>Wählen Sie <strong>Ihre</strong> Organisation.</p>'
    );
    expect(rendered('Titel<p>Text</p>Nachsatz').innerHTML).toBe(
      '<p>Titel</p><p>Text</p><p>Nachsatz</p>'
    );
  });

  it('adds no paragraph for the whitespace between blocks', () => {
    expect(rendered('<p>One</p>\n  <p>Two</p>\n').innerHTML).toBe('<p>One</p><p>Two</p>');
  });

  it('does not take inherited object keys for allowlisted tags', () => {
    expect(rendered('<constructor>Text</constructor>').innerHTML).toBe('<p>Text</p>');
    expect(rendered('<p><constructor>Text</constructor></p>').innerHTML).toBe('<p>Text</p>');
  });

  it('keeps escaped markup as text', () => {
    const host = rendered('<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>');

    expect(host.querySelector('script')).toBeNull();
    expect(host.textContent).toBe('<script>alert(1)</script>');
  });

  it('renders plain text as one paragraph of text', () => {
    expect(rendered('Plain text &amp; more').innerHTML).toBe('<p>Plain text &amp; more</p>');
  });

  it('renders blocks as block spans when inline, so it fits inside a label or paragraph', () => {
    const host = rendered('<p>One</p><p><strong>Two</strong></p><p></p>', true);

    expect(host.querySelector('p')).toBeNull();
    expect(host.innerHTML).toBe(
      '<span class="block">One</span><span class="block"><strong>Two</strong></span>'
    );
  });

  it('leaves text outside any block alone when inline', () => {
    expect(rendered('Ich <em>stimme</em> zu.', true).innerHTML).toBe('Ich <em>stimme</em> zu.');
  });

  describe('against script injection', () => {
    it.each([
      ['a script element', '<p>Hi</p><script>alert(1)</script>'],
      ['a script inside a paragraph', '<p>Hi<script>alert(1)</script></p>'],
      ['a style element', '<style>p{color:red}</style><p>Hi</p>'],
      ['an iframe', '<iframe src="https://evil.test">alert(1)</iframe><p>Hi</p>'],
      ['an svg', '<svg onload="alert(1)"><script>alert(1)</script><text>x</text></svg><p>Hi</p>'],
      ['a math element', '<math><mi xlink:href="javascript:alert(1)">x</mi></math><p>Hi</p>'],
      ['an image with onerror', '<img src="x" onerror="alert(1)"><p>Hi</p>'],
      ['a template', '<template><img src=x onerror=alert(1)></template><p>Hi</p>'],
      ['a noscript', '<p>Hi</p><noscript><p>alert(1)</p><script>alert(1)</script></noscript>'],
      ['an object and an embed', '<object data="x">alert</object><embed src="x"><p>Hi</p>'],
      [
        'a form control',
        '<textarea>alert(1)</textarea><select><option>alert</option></select><p>Hi</p>',
      ],
    ])('removes %s with its content', (_label, html) => {
      expect(rendered(html).innerHTML).toBe('<p>Hi</p>');
    });

    it('copies no attribute but a link href', () => {
      const host = rendered(
        '<p onclick="alert(1)" style="color:red" class="x" id="y">Hi <a href="https://x.test/" onmouseover="alert(1)" style="x" class="y">x</a></p>'
      );

      expect(host.querySelector('p')?.attributes).toHaveLength(0);
      expect(host.innerHTML).not.toMatch(/\son\w+=|style=|class="[xy]"|id=/);
      expect(host.querySelector('a')).toHaveAttribute('href', 'https://x.test/');
    });

    it.each([
      'javascript:alert(1)',
      ' JaVaScRiPt:alert(1)',
      'java\tscript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      plainHttp('https://www.kassel.de/'),
      '/relative',
      '',
      'https://dialog.kassel.de@evil.example/',
      'https://user:secret@www.kassel.de/',
    ])('unwraps a link to %j into its text', (href) => {
      const host = rendered(`<p><a href="${href}">Klick</a></p>`);

      expect(host.querySelector('a')).toBeNull();
      expect(host.innerHTML).toBe('<p>Klick</p>');
    });

    it('unwraps a link without href into its text', () => {
      expect(rendered('<p><a>Klick</a></p>').innerHTML).toBe('<p>Klick</p>');
    });
  });
});
