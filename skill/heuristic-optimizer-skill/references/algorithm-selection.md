# Algorithm Selection Guide

- TSP/配送経路: Nearest Neighbor + 2-opt/3-opt、SA、Tabu Search
- 割当: Greedy + swap/local search、必要なら整数計画との比較
- スケジューリング: Dispatching rule + local search/SA/GA
- ナップサック: Greedy、local search、GA（厳密解との比較が容易）
- 多目的問題: 重み付き目的関数、Paretoベース手法を検討

選定時は、問題サイズ、制約の強さ、許容計算時間、必要な解品質、再現性を記録する。
