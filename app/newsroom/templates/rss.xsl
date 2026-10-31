<?xml version="1.0" encoding="UTF-8"?>
<!-- Styles /rss.xml in browsers. Feed readers ignore this and read the raw RSS. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" encoding="UTF-8" indent="yes"/>

  <xsl:template match="/rss/channel">
    <html lang="en">
      <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
        <title><xsl:value-of select="title"/> - RSS Feed</title>
        <style>
          body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; background: #f8f8f8;
                 color: #333; line-height: 1.6; }
          header { background: #1a1a1a; color: #fff; padding: 20px 0; border-bottom: 5px solid #0056b3; }
          .wrap { max-width: 800px; margin: auto; padding: 0 20px; }
          header h1 { margin: 0; font-family: Georgia, serif; font-size: 1.6em; }
          header p { margin: 5px 0 0; color: #ccc; }
          .notice { background: #fff; border-left: 4px solid #0056b3; padding: 12px 16px;
                    margin: 25px 0; border-radius: 4px; font-size: 0.95em; }
          .notice code { background: #eee; padding: 2px 6px; border-radius: 3px; }
          .item { background: #fff; border-radius: 8px; padding: 18px 22px; margin-bottom: 18px;
                  box-shadow: 0 2px 4px rgba(0,0,0,0.06); }
          .item h2 { margin: 0 0 6px; font-family: Georgia, serif; font-size: 1.2em; line-height: 1.3; }
          .item h2 a { color: #333; text-decoration: none; }
          .item h2 a:hover { color: #0056b3; }
          .meta { font-size: 0.85em; color: #666; margin-bottom: 8px; }
          .tag { font-weight: 600; color: #0056b3; }
          footer { text-align: center; color: #666; font-size: 0.85em; padding: 20px 0 40px; }
          footer a { color: #0056b3; }
        </style>
      </head>
      <body>
        <header>
          <div class="wrap">
            <h1><xsl:value-of select="title"/></h1>
            <p><xsl:value-of select="description"/></p>
          </div>
        </header>
        <div class="wrap">
          <div class="notice">
            This is an RSS feed. Copy this page's address into a feed reader to subscribe:
            <code><xsl:value-of select="link"/>rss.xml</code>
          </div>
          <xsl:for-each select="item">
            <div class="item">
              <h2><a href="{link}" target="_blank" rel="noopener noreferrer"><xsl:value-of select="title"/></a></h2>
              <div class="meta">
                <xsl:value-of select="pubDate"/> |
                <span class="tag"><xsl:value-of select="category"/></span>
              </div>
              <div><xsl:value-of select="description"/></div>
            </div>
          </xsl:for-each>
          <footer>
            Last build: <xsl:value-of select="lastBuildDate"/> |
            <a href="/">Back to the newsroom</a>
          </footer>
        </div>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
