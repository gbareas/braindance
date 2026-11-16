# Choosing the chart

Read this before deciding what kind of figure to draw, and again when a reviewer questions the choice. If the user has already fixed the chart type, keep it and only apply the rules in section 2.

Start from the shape of the data, not from a chart you have in mind: how many variables, which are numeric and which are categories, whether one of them is ordered (time, dose, frequency), and how many observations there are per group.

## 1. From data to chart

"First choice" is what to draw unless there is a reason not to. Charts that rarely belong in a paper (pie, doughnut, word cloud, 3D, radar) are left out on purpose.

### Numeric only

| Your data | First choice | Alternatives | Watch out |
|---|---|---|---|
| One variable | Histogram | Density curve | Try several bin widths before settling |
| Two variables, not ordered, up to about 2000 points | Scatter | Scatter with marginal histograms | Aspect ratio changes how strong a correlation looks |
| Two variables, not ordered, many points | 2D density (hexbin or 2D histogram) | Scatter with small transparent markers; contours | Overplotting hides where the points are |
| Two variables, one ordered | Line | Connected scatter when points are few; area for a single series | Join points only where the quantity is continuous between them |
| Three variables | Scatter with colour for the third | Bubble (size for the third) | Size is read poorly; scale bubbles by area, never radius |
| Several variables, not ordered | Correlation matrix as a heatmap | Scatter matrix, PCA projection | Reorder rows and columns so structure shows |
| Several variables, ordered | Lines on shared axes | Small multiples; stacked area for parts of a whole | More than about five lines becomes spaghetti |

### One numeric variable against categories

| Your data | First choice | Alternatives | Watch out |
|---|---|---|---|
| One value per group | Dot plot or bars, sorted by value | Lollipop | Bars start at zero; use dots if you need a cut axis |
| Several observations per group, few groups | Box plot with the individual points on top | Violin when samples are large; overlaid histograms or densities for up to about four groups | A box plot alone hides sample size and shape |
| Several observations per group, many groups | Ridgeline or small multiples | Sorted box plots | Violins get too thin to read |
| One value per combination of two category variables | Grouped bars or dots | Heatmap; small multiples | Stacked bars only compare the bottom segment well |
| Several observations per combination | Grouped box plots | Small multiples | State n per group |
| Value against an ordered variable, per group | One line per group | Small multiples, with the others in grey | See "spaghetti" below |

### Time series

Use a line for one series and lines on shared axes for a few. For many series, use small multiples or a heatmap (series by time). Keep time intervals to scale on the axis: unevenly spaced samples stay unevenly spaced.

### Matrices and fields

A 2D array is a heatmap with a labelled colourbar. Sequential data takes a sequential map, data with a meaningful midpoint takes a diverging map centred on that midpoint.

### Relationships and hierarchies

Networks, flows and trees (node-link diagrams, Sankey, chord, dendrogram, treemap) are schematics rather than plots and are outside this skill for now. An adjacency matrix can be drawn as a heatmap.

## 2. Rules that hold whatever the chart

Rules marked **[checked]** are measured by `check_figure.py`. The others need a look.

### Showing the data honestly

- Show individual observations whenever there are few enough to see; a summary alone can hide very different distributions.
- If you draw error bars, the caption must say what they are (standard deviation, standard error or a confidence interval) and give n. These differ a lot in size, and the reader cannot tell which is drawn.
- Bars start at zero. For lines and points the axis may be cut to show the variation; there is no consensus that it must start at zero, so choose the range that shows the data and say so if it could mislead.
- Avoid two different y-axes in one panel; use two stacked panels sharing the x-axis.
- No 3D effects. A third variable goes to colour, size or a second panel.
- Check for subgroups before showing a pooled trend: a trend can reverse within each group.
- Sort categories by value unless they have a natural order.
- Every point that was measured appears in the figure, or the caption says what was left out. **[checked]** (points outside the axis limits, values a log axis cannot show, series missing from the figure)

### Too much in one panel

- More than about five lines: highlight the one the text discusses and draw the rest in grey, or use small multiples, or both (all lines in grey in every panel, one highlighted per panel).
- Too many points: smaller markers, transparency, then a 2D density. Sampling is acceptable if the caption says so. Add marginal distributions when the density matters.
- More than about four overlaid distributions: use ridgelines or small multiples.
- Small multiples share their axes when the reader should compare panels, and are stacked along the axis they do not share.

### Colour

- Colour encodes something or it is not used. The same series keeps the same colour in every figure of the paper.
- Sequential map for magnitudes, diverging map for data with a meaningful midpoint, distinct colours (not a gradient) for categories. Never rainbow. **[checked]** (`jet` and relatives fail)
- Series must stay distinct without colour: vary line style or marker too. **[checked]**

### Labels and annotation

- Label curves directly when there is room; a legend is the fallback.
- Nothing sits on the data: not the legend, not a panel label, not an annotation. **[checked]**
- Horizontal text wherever possible; do not rotate category labels, turn the chart instead.
- Round numbers to the precision that matters, and do not label every tick. **[checked]** (overlapping tick labels are reported)
- One short annotation that points at the feature the text discusses is worth more than a longer caption.

### Economy

- Remove what carries no information: boxes around legends, heavy grids, backgrounds, duplicate axis labels on shared axes.
- Do not make the reader do arithmetic. If the claim is a difference or a ratio, plot the difference or the ratio.

## Source

The decision tables and most of the rules above are adapted from [From Data to Viz](https://www.data-to-viz.com) by Yan Holtz and Conor Healy (MIT licence, copyright 2017 Yan Holtz), narrowed to the chart types and concerns of figures in scientific papers. For a worked example of comparing chart options on one dataset, see the "Story" pages on that site.
