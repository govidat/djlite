Mapping rules applied
HTML <section> → Level 10 (Section)
Every top-level <section> becomes one Level 10 node. The section's own classes (e.g. py-16 px-4 bg-base-200) go on css_class at Level 10. The slug is derived from the section's semantic meaning (hero, our-story, values, team, timeline, cta).
Containing <div class="max-w-* mx-auto"> → Level 20 (Row)
The centring wrapper div directly inside a section maps to Level 20. Its constraint classes (max-w-4xl mx-auto) sit on the Row's css_class.
Layout-dividing <div> (flex/grid rows) → Level 30 (Col)
Any div that introduces a layout split — flex flex-col md:flex-row, grid grid-cols-3 — becomes a Level 30. The grid/flex classes belong here. When a section has both a heading row and a content grid (Values, Team), that produces two Level 30 siblings under the same Level 20.
Leaf content wrapper → Level 40 (Cell) + Component
The innermost content unit (a card div, a person flex-column, the hero-content div) becomes a Level 40 cell, and its contents become the component. The comp_id is inferred from the DaisyUI pattern in use:
HTML patterncomp_id.hero / .hero-contentheroPlain paragraphs + headingrichtext.stats / .statstats.card / .card-bodycardAvatar placeholder + name/role/bioperson<ul class="timeline">timelineCTA heading + buttonscta

Three design decisions worth noting
stats and timeline use config instead of slots. Their data is strongly structured (fixed fields: title/value/desc; year/text/side) and doesn't need multilingual ComptextBlock plumbing in Phase 1. Putting them in config keeps the slot list clean. When you add i18n for stats labels later, you'd move them to text slots.
Buttons in the CTA become textblocks with href_page. This reuses the existing href_page field on ComptextBlock rather than inventing a new slot type. The block_id prefix btn_ distinguishes them from copy blocks in the renderer.
Two Level 30 rows under Values and Team. The heading <h2> is a separate richtext component above the grid rather than being embedded inside the grid component. This mirrors how your existing hero example separates the figure and text slots — the heading is independently editable and hideable without touching the card grid.

What still requires a renderer template per comp_id
The JSON is complete, but your fetch_clientstatic() renderer and the Track B templates need a {% include %} or cotton component for each comp_id (stats, person, timeline, cta, richtext). The hero and card templates likely already exist from Phase 2 work.

Result:
{
  "layouts": [

    {
      "level": 10,
      "slug": "hero",
      "order": 1,
      "css_class": "hero min-h-64 bg-primary text-primary-content",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "",
          "children": [
            {
              "level": 30,
              "slug": "a",
              "order": 1,
              "css_class": "",
              "children": [
                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "hero",
                    "ltext": "Hero Section",
                    "css_class": "hero-content text-center",
                    "hero_overlay": false,
                    "config": { "max_width": "max-w-2xl" },
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "title",
                            "order": 1,
                            "css_class": "text-5xl font-bold mb-4",
                            "ltext": "Hero Title",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "About Us V2"
                              }
                            ]
                          },
                          {
                            "block_id": "subtitle",
                            "order": 2,
                            "css_class": "text-xl opacity-80",
                            "ltext": "Hero Subtitle",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "A passionate team building great products for our customers since 2018."
                              }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
              ]
            }
          ]
        }
      ]
    },

    {
      "level": 10,
      "slug": "our-story",
      "order": 2,
      "css_class": "py-16 px-4 bg-base-100",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "max-w-4xl mx-auto",
          "children": [
            {
              "level": 30,
              "slug": "story-text",
              "order": 1,
              "css_class": "flex flex-col md:flex-row gap-12 items-center",
              "children": [

                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "flex-1",
                  "component": {
                    "comp_id": "richtext",
                    "ltext": "Our Story Text",
                    "css_class": "",
                    "hero_overlay": false,
                    "config": {},
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "heading",
                            "order": 1,
                            "css_class": "text-3xl font-bold text-base-content mb-6",
                            "ltext": "Section Heading",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "Our Story"
                              }
                            ]
                          },
                          {
                            "block_id": "para1",
                            "order": 2,
                            "css_class": "text-base-content/70 text-lg leading-relaxed mb-4",
                            "ltext": "Story paragraph 1",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "Founded with a simple belief — that great service and quality products should be accessible to everyone — we started as a small team with big ambitions. Today we serve hundreds of happy customers across the region."
                              }
                            ]
                          },
                          {
                            "block_id": "para2",
                            "order": 3,
                            "css_class": "text-base-content/70 text-lg leading-relaxed",
                            "ltext": "Story paragraph 2",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "Every product we carry is carefully selected, and every interaction with our team is designed to leave you with a smile."
                              }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                },

                {
                  "level": 40,
                  "slug": "b",
                  "order": 2,
                  "css_class": "flex-1 flex justify-center",
                  "component": {
                    "comp_id": "stats",
                    "ltext": "Story Stats",
                    "css_class": "stats stats-vertical shadow",
                    "hero_overlay": false,
                    "config": {
                      "stats": [
                        {
                          "title": "Happy Customers",
                          "value": "500+",
                          "value_css": "text-primary",
                          "desc": "Across the region"
                        },
                        {
                          "title": "Years in Business",
                          "value": "6",
                          "value_css": "text-secondary",
                          "desc": "Since 2018"
                        },
                        {
                          "title": "Team Members",
                          "value": "12",
                          "value_css": "text-accent",
                          "desc": "And growing"
                        }
                      ]
                    },
                    "hidden": false,
                    "order": 2,
                    "slots": []
                  }
                }

              ]
            }
          ]
        }
      ]
    },

    {
      "level": 10,
      "slug": "values",
      "order": 3,
      "css_class": "py-16 px-4 bg-base-200",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "max-w-4xl mx-auto",
          "children": [
            {
              "level": 30,
              "slug": "values-heading",
              "order": 1,
              "css_class": "",
              "children": [
                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "richtext",
                    "ltext": "Values Heading",
                    "css_class": "",
                    "hero_overlay": false,
                    "config": {},
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "heading",
                            "order": 1,
                            "css_class": "text-3xl font-bold text-base-content text-center mb-12",
                            "ltext": "Section Heading",
                            "href_page": "",
                            "items": [
                              {
                                "type": "text",
                                "order": 1,
                                "css_class": "",
                                "value": "What We Stand For"
                              }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
              ]
            },
            {
              "level": 30,
              "slug": "values-cards",
              "order": 2,
              "css_class": "grid grid-cols-1 md:grid-cols-3 gap-6",
              "children": [

                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "card",
                    "ltext": "Value — Trust",
                    "css_class": "card bg-base-100 shadow",
                    "hero_overlay": false,
                    "config": { "align": "items-center text-center" },
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "icon",
                            "order": 1,
                            "css_class": "badge badge-primary badge-lg p-4 mb-4 text-2xl",
                            "ltext": "Card icon",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "🤝" }
                            ]
                          },
                          {
                            "block_id": "title",
                            "order": 2,
                            "css_class": "card-title",
                            "ltext": "Card title",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Trust" }
                            ]
                          },
                          {
                            "block_id": "body",
                            "order": 3,
                            "css_class": "text-base-content/70",
                            "ltext": "Card body",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "We build lasting relationships through honesty and transparency in everything we do." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                },

                {
                  "level": 40,
                  "slug": "b",
                  "order": 2,
                  "css_class": "",
                  "component": {
                    "comp_id": "card",
                    "ltext": "Value — Quality",
                    "css_class": "card bg-base-100 shadow",
                    "hero_overlay": false,
                    "config": { "align": "items-center text-center" },
                    "hidden": false,
                    "order": 2,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "icon",
                            "order": 1,
                            "css_class": "badge badge-secondary badge-lg p-4 mb-4 text-2xl",
                            "ltext": "Card icon",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "⭐" }
                            ]
                          },
                          {
                            "block_id": "title",
                            "order": 2,
                            "css_class": "card-title",
                            "ltext": "Card title",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Quality" }
                            ]
                          },
                          {
                            "block_id": "body",
                            "order": 3,
                            "css_class": "text-base-content/70",
                            "ltext": "Card body",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Every product and service we offer meets a standard we are genuinely proud of." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                },

                {
                  "level": 40,
                  "slug": "c",
                  "order": 3,
                  "css_class": "",
                  "component": {
                    "comp_id": "card",
                    "ltext": "Value — Innovation",
                    "css_class": "card bg-base-100 shadow",
                    "hero_overlay": false,
                    "config": { "align": "items-center text-center" },
                    "hidden": false,
                    "order": 3,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "icon",
                            "order": 1,
                            "css_class": "badge badge-accent badge-lg p-4 mb-4 text-2xl",
                            "ltext": "Card icon",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "💡" }
                            ]
                          },
                          {
                            "block_id": "title",
                            "order": 2,
                            "css_class": "card-title",
                            "ltext": "Card title",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Innovation" }
                            ]
                          },
                          {
                            "block_id": "body",
                            "order": 3,
                            "css_class": "text-base-content/70",
                            "ltext": "Card body",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "We keep improving and finding better ways to serve our customers every day." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }

              ]
            }
          ]
        }
      ]
    },

    {
      "level": 10,
      "slug": "team",
      "order": 4,
      "css_class": "py-16 px-4 bg-base-100",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "max-w-4xl mx-auto",
          "children": [
            {
              "level": 30,
              "slug": "team-heading",
              "order": 1,
              "css_class": "",
              "children": [
                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "richtext",
                    "ltext": "Team Heading",
                    "css_class": "",
                    "hero_overlay": false,
                    "config": {},
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "heading",
                            "order": 1,
                            "css_class": "text-3xl font-bold text-base-content text-center mb-12",
                            "ltext": "Section Heading",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Meet the Team" }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
              ]
            },
            {
              "level": 30,
              "slug": "team-cards",
              "order": 2,
              "css_class": "grid grid-cols-1 md:grid-cols-3 gap-8",
              "children": [

                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "person",
                    "ltext": "Team — Priya Sharma",
                    "css_class": "flex flex-col items-center text-center gap-4",
                    "hero_overlay": false,
                    "config": {
                      "avatar_initials": "PS",
                      "avatar_bg": "bg-primary",
                      "avatar_text": "text-primary-content"
                    },
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "name",
                            "order": 1,
                            "css_class": "font-bold text-lg text-base-content",
                            "ltext": "Person name",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Priya Sharma" }
                            ]
                          },
                          {
                            "block_id": "role",
                            "order": 2,
                            "css_class": "text-base-content/60 text-sm",
                            "ltext": "Person role",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Founder & CEO" }
                            ]
                          },
                          {
                            "block_id": "bio",
                            "order": 3,
                            "css_class": "text-base-content/70 text-sm",
                            "ltext": "Person bio",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Passionate about building products that make a real difference in people's daily lives." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                },

                {
                  "level": 40,
                  "slug": "b",
                  "order": 2,
                  "css_class": "",
                  "component": {
                    "comp_id": "person",
                    "ltext": "Team — Arjun Menon",
                    "css_class": "flex flex-col items-center text-center gap-4",
                    "hero_overlay": false,
                    "config": {
                      "avatar_initials": "AM",
                      "avatar_bg": "bg-secondary",
                      "avatar_text": "text-secondary-content"
                    },
                    "hidden": false,
                    "order": 2,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "name",
                            "order": 1,
                            "css_class": "font-bold text-lg text-base-content",
                            "ltext": "Person name",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Arjun Menon" }
                            ]
                          },
                          {
                            "block_id": "role",
                            "order": 2,
                            "css_class": "text-base-content/60 text-sm",
                            "ltext": "Person role",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Head of Operations" }
                            ]
                          },
                          {
                            "block_id": "bio",
                            "order": 3,
                            "css_class": "text-base-content/70 text-sm",
                            "ltext": "Person bio",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Keeps everything running smoothly so our team can focus on what matters most — the customer." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                },

                {
                  "level": 40,
                  "slug": "c",
                  "order": 3,
                  "css_class": "",
                  "component": {
                    "comp_id": "person",
                    "ltext": "Team — Kavya Nair",
                    "css_class": "flex flex-col items-center text-center gap-4",
                    "hero_overlay": false,
                    "config": {
                      "avatar_initials": "KN",
                      "avatar_bg": "bg-accent",
                      "avatar_text": "text-accent-content"
                    },
                    "hidden": false,
                    "order": 3,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "name",
                            "order": 1,
                            "css_class": "font-bold text-lg text-base-content",
                            "ltext": "Person name",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Kavya Nair" }
                            ]
                          },
                          {
                            "block_id": "role",
                            "order": 2,
                            "css_class": "text-base-content/60 text-sm",
                            "ltext": "Person role",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Customer Experience" }
                            ]
                          },
                          {
                            "block_id": "bio",
                            "order": 3,
                            "css_class": "text-base-content/70 text-sm",
                            "ltext": "Person bio",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Dedicated to making every customer interaction feel personal, warm, and effortless." }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }

              ]
            }
          ]
        }
      ]
    },

    {
      "level": 10,
      "slug": "timeline",
      "order": 5,
      "css_class": "py-16 px-4 bg-base-200",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "max-w-2xl mx-auto",
          "children": [
            {
              "level": 30,
              "slug": "a",
              "order": 1,
              "css_class": "",
              "children": [
                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "timeline",
                    "ltext": "Journey Timeline",
                    "css_class": "timeline timeline-vertical",
                    "hero_overlay": false,
                    "config": {
                      "heading": "Our Journey",
                      "heading_css": "text-3xl font-bold text-base-content text-center mb-12",
                      "items": [
                        {
                          "year": "2018",
                          "badge_css": "badge-primary",
                          "line_css": "bg-primary",
                          "side": "start",
                          "text": "Founded in Bengaluru"
                        },
                        {
                          "year": "2020",
                          "badge_css": "badge-primary",
                          "line_css": "bg-primary",
                          "side": "end",
                          "text": "Reached 100 customers"
                        },
                        {
                          "year": "2022",
                          "badge_css": "badge-secondary",
                          "line_css": "bg-secondary",
                          "side": "start",
                          "text": "Expanded to 3 locations"
                        },
                        {
                          "year": "2024",
                          "badge_css": "badge-accent",
                          "line_css": "",
                          "side": "end",
                          "text": "Launched online platform"
                        }
                      ]
                    },
                    "hidden": false,
                    "order": 1,
                    "slots": []
                  }
                }
              ]
            }
          ]
        }
      ]
    },

    {
      "level": 10,
      "slug": "cta",
      "order": 6,
      "css_class": "py-16 px-4 bg-primary text-primary-content text-center",
      "children": [
        {
          "level": 20,
          "slug": "a",
          "order": 1,
          "css_class": "max-w-2xl mx-auto",
          "children": [
            {
              "level": 30,
              "slug": "a",
              "order": 1,
              "css_class": "",
              "children": [
                {
                  "level": 40,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "component": {
                    "comp_id": "cta",
                    "ltext": "CTA Block",
                    "css_class": "",
                    "hero_overlay": false,
                    "config": {
                      "button_class": "btn btn-outline text-primary-content border-primary-content hover:bg-primary-content hover:text-primary",
                      "button_layout": "flex flex-col sm:flex-row gap-4 justify-center"
                    },
                    "hidden": false,
                    "order": 1,
                    "slots": [
                      {
                        "slot_type": "text",
                        "order": 1,
                        "hidden": false,
                        "accordion_checked": false,
                        "textblocks": [
                          {
                            "block_id": "heading",
                            "order": 1,
                            "css_class": "text-3xl font-bold mb-4",
                            "ltext": "CTA Heading",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Want to Get in Touch?" }
                            ]
                          },
                          {
                            "block_id": "subtext",
                            "order": 2,
                            "css_class": "text-xl opacity-80 mb-8",
                            "ltext": "CTA subtext",
                            "href_page": "",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "We would love to hear from you." }
                            ]
                          },
                          {
                            "block_id": "btn_email",
                            "order": 3,
                            "css_class": "btn btn-outline text-primary-content border-primary-content hover:bg-primary-content hover:text-primary",
                            "ltext": "CTA button 1",
                            "href_page": "mailto:hello@example.com",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Email Us" }
                            ]
                          },
                          {
                            "block_id": "btn_store",
                            "order": 4,
                            "css_class": "btn btn-outline text-primary-content border-primary-content hover:bg-primary-content hover:text-primary",
                            "ltext": "CTA button 2",
                            "href_page": "#",
                            "items": [
                              { "type": "text", "order": 1, "css_class": "", "value": "Visit a Store" }
                            ]
                          }
                        ]
                      }
                    ]
                  }
                }
              ]
            }
          ]
        }
      ]
    }

  ]
}

Input html:
<!-- 
  About page — Tailwind + DaisyUI only. No inline styles.
  Paste into PageContent.html in Django Admin.
  Theme switching works because all colours use DaisyUI semantic tokens.
  
  How to get this from Google Stitch:
  Prompt: "Design an about page for a small business. 
           Use only Tailwind CSS utility classes and DaisyUI component classes.
           No inline styles. No custom CSS. No React. Plain HTML only."
-->

<main>

  <!-- ── Hero ───────────────────────────────────────────────────── -->
  <section class="hero min-h-64 bg-primary text-primary-content">
    <div class="hero-content text-center">
      <div class="max-w-2xl">
        <h1 class="text-5xl font-bold mb-4">About Us V2</h1>
        <p class="text-xl opacity-80">
          A passionate team building great products for our customers since 2018.
        </p>
      </div>
    </div>
  </section>

  <!-- ── Our Story ──────────────────────────────────────────────── -->
  <section class="py-16 px-4 bg-base-100">
    <div class="max-w-4xl mx-auto">
      <div class="flex flex-col md:flex-row gap-12 items-center">

        <div class="flex-1">
          <h2 class="text-3xl font-bold text-base-content mb-6">Our Story</h2>
          <p class="text-base-content/70 text-lg leading-relaxed mb-4">
            Founded with a simple belief — that great service and quality products
            should be accessible to everyone — we started as a small team with big
            ambitions. Today we serve hundreds of happy customers across the region.
          </p>
          <p class="text-base-content/70 text-lg leading-relaxed">
            Every product we carry is carefully selected, and every interaction with
            our team is designed to leave you with a smile.
          </p>
        </div>

        <div class="flex-1 flex justify-center">
          <div class="stats stats-vertical shadow">
            <div class="stat">
              <div class="stat-title">Happy Customers</div>
              <div class="stat-value text-primary">500+</div>
              <div class="stat-desc">Across the region</div>
            </div>
            <div class="stat">
              <div class="stat-title">Years in Business</div>
              <div class="stat-value text-secondary">6</div>
              <div class="stat-desc">Since 2018</div>
            </div>
            <div class="stat">
              <div class="stat-title">Team Members</div>
              <div class="stat-value text-accent">12</div>
              <div class="stat-desc">And growing</div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </section>

  <!-- ── Values ─────────────────────────────────────────────────── -->
  <section class="py-16 px-4 bg-base-200">
    <div class="max-w-4xl mx-auto">
      <h2 class="text-3xl font-bold text-base-content text-center mb-12">
        What We Stand For
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">

        <div class="card bg-base-100 shadow">
          <div class="card-body items-center text-center">
            <div class="badge badge-primary badge-lg p-4 mb-4 text-2xl">🤝</div>
            <h3 class="card-title">Trust</h3>
            <p class="text-base-content/70">
              We build lasting relationships through honesty and transparency
              in everything we do.
            </p>
          </div>
        </div>

        <div class="card bg-base-100 shadow">
          <div class="card-body items-center text-center">
            <div class="badge badge-secondary badge-lg p-4 mb-4 text-2xl">⭐</div>
            <h3 class="card-title">Quality</h3>
            <p class="text-base-content/70">
              Every product and service we offer meets a standard we are
              genuinely proud of.
            </p>
          </div>
        </div>

        <div class="card bg-base-100 shadow">
          <div class="card-body items-center text-center">
            <div class="badge badge-accent badge-lg p-4 mb-4 text-2xl">💡</div>
            <h3 class="card-title">Innovation</h3>
            <p class="text-base-content/70">
              We keep improving and finding better ways to serve our customers
              every day.
            </p>
          </div>
        </div>

      </div>
    </div>
  </section>

  <!-- ── Team ───────────────────────────────────────────────────── -->
  <section class="py-16 px-4 bg-base-100">
    <div class="max-w-4xl mx-auto">
      <h2 class="text-3xl font-bold text-base-content text-center mb-12">
        Meet the Team
      </h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-8">

        <div class="flex flex-col items-center text-center gap-4">
          <div class="avatar placeholder">
            <div class="bg-primary text-primary-content rounded-full w-24">
              <span class="text-3xl">PS</span>
            </div>
          </div>
          <div>
            <p class="font-bold text-lg text-base-content">Priya Sharma</p>
            <p class="text-base-content/60 text-sm">Founder &amp; CEO</p>
          </div>
          <p class="text-base-content/70 text-sm">
            Passionate about building products that make a real difference
            in people's daily lives.
          </p>
        </div>

        <div class="flex flex-col items-center text-center gap-4">
          <div class="avatar placeholder">
            <div class="bg-secondary text-secondary-content rounded-full w-24">
              <span class="text-3xl">AM</span>
            </div>
          </div>
          <div>
            <p class="font-bold text-lg text-base-content">Arjun Menon</p>
            <p class="text-base-content/60 text-sm">Head of Operations</p>
          </div>
          <p class="text-base-content/70 text-sm">
            Keeps everything running smoothly so our team can focus on
            what matters most — the customer.
          </p>
        </div>

        <div class="flex flex-col items-center text-center gap-4">
          <div class="avatar placeholder">
            <div class="bg-accent text-accent-content rounded-full w-24">
              <span class="text-3xl">KN</span>
            </div>
          </div>
          <div>
            <p class="font-bold text-lg text-base-content">Kavya Nair</p>
            <p class="text-base-content/60 text-sm">Customer Experience</p>
          </div>
          <p class="text-base-content/70 text-sm">
            Dedicated to making every customer interaction feel personal,
            warm, and effortless.
          </p>
        </div>

      </div>
    </div>
  </section>

  <!-- ── Timeline ───────────────────────────────────────────────── -->
  <section class="py-16 px-4 bg-base-200">
    <div class="max-w-2xl mx-auto">
      <h2 class="text-3xl font-bold text-base-content text-center mb-12">
        Our Journey
      </h2>
      <ul class="timeline timeline-vertical">
        <li>
          <div class="timeline-start timeline-box">Founded in Bengaluru</div>
          <div class="timeline-middle">
            <div class="badge badge-primary">2018</div>
          </div>
          <hr class="bg-primary"/>
        </li>
        <li>
          <hr class="bg-primary"/>
          <div class="timeline-middle">
            <div class="badge badge-primary">2020</div>
          </div>
          <div class="timeline-end timeline-box">Reached 100 customers</div>
          <hr class="bg-primary"/>
        </li>
        <li>
          <hr class="bg-primary"/>
          <div class="timeline-middle">
            <div class="badge badge-secondary">2022</div>
          </div>
          <div class="timeline-start timeline-box">Expanded to 3 locations</div>
          <hr class="bg-secondary"/>
        </li>
        <li>
          <hr class="bg-secondary"/>
          <div class="timeline-middle">
            <div class="badge badge-accent">2024</div>
          </div>
          <div class="timeline-end timeline-box">Launched online platform</div>
        </li>
      </ul>
    </div>
  </section>

  <!-- ── CTA ────────────────────────────────────────────────────── -->
  <section class="py-16 px-4 bg-primary text-primary-content text-center">
    <div class="max-w-2xl mx-auto">
      <h2 class="text-3xl font-bold mb-4">Want to Get in Touch?</h2>
      <p class="text-xl opacity-80 mb-8">
        We would love to hear from you.
      </p>
      <div class="flex flex-col sm:flex-row gap-4 justify-center">
        <a href="mailto:hello@example.com"
           class="btn btn-outline text-primary-content border-primary-content
                  hover:bg-primary-content hover:text-primary">
          Email Us
        </a>
        <a href="#"
           class="btn btn-outline text-primary-content border-primary-content
                  hover:bg-primary-content hover:text-primary">
          Visit a Store
        </a>
      </div>
    </div>
  </section>

</main>
