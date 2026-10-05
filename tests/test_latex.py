import gzip
import io
import tarfile

from citecheck import latex

BIB = r"""
@article{smith2020,
  title = {Deep {Residual} Learning at Scale},
  author = {Smith, Jane and Doe, John},
  journal = {arXiv preprint arXiv:2006.01234},
  year = {2020},
}
@inproceedings{lee2021, title="Attention Everywhere", author="Lee, Kim", booktitle="NeurIPS", year=2021,
  doi = {10.5555/12345.678}}
@misc{nobody, note={no title here}}
"""

BBL = r"""
\begin{thebibliography}{2}
\bibitem[{Vaswani et~al.(2017)}]{vaswani2017}
Ashish Vaswani, Noam Shazeer.
\newblock Attention is all you need.
\newblock In \emph{NeurIPS}, 2017. arXiv:1706.03762v5.
\bibitem{brown2020}
Tom Brown.
\newblock Language models are few-shot learners.
\newblock 2020.
\end{thebibliography}
"""

TEX = r"""
\documentclass{article}
\begin{document}
\section{Introduction}
Residual networks train much deeper models than plain networks of the same width \citep{smith2020}. % a comment \cite{lee2021}
We follow prior work \cite{smith2020, lee2021} in many ways that are not relevant to this test case.
Attention mechanisms improve translation quality substantially on standard benchmarks, e.g. WMT \citet[p.~3]{lee2021}.
\begin{figure}Caption citing \cite{smith2020} that must be ignored by the parser here.\end{figure}
Unknown references like \cite{missing} are dropped from the output pairs entirely here.
Short \cite{lee2021}.
\end{document}
"""


def test_parse_bib_fields_and_ids():
    refs = latex.parse_bib(BIB)
    assert refs["smith2020"]["title"] == "Deep Residual Learning at Scale"
    assert refs["smith2020"]["arxiv_id"] == "2006.01234"
    assert refs["lee2021"]["title"] == "Attention Everywhere"
    assert refs["lee2021"]["doi"] == "10.5555/12345.678"
    assert refs["nobody"]["title"] == ""


def test_parse_bbl_title_and_arxiv_id():
    refs = latex.parse_bbl(BBL)
    assert refs["vaswani2017"]["title"] == "Attention is all you need"
    assert refs["vaswani2017"]["arxiv_id"] == "1706.03762"
    assert refs["brown2020"]["title"] == "Language models are few-shot learners"
    assert refs["brown2020"]["arxiv_id"] is None


def test_citation_pairs_single_citation_sentences_only():
    pairs, refs = latex.citation_pairs({"main.tex": TEX, "refs.bib": BIB})
    claims = {p["claim"]: p["key"] for p in pairs}
    assert claims == {
        "Residual networks train much deeper models than plain networks of the same width [CITATION].": "smith2020",
        "Attention mechanisms improve translation quality substantially on standard benchmarks, e.g. WMT [CITATION].":
            "lee2021",
    }
    # the multi-citation sentence, the figure caption, the comment, the unknown key,
    # and the too-short sentence are all excluded


def test_bibitems_inside_tex_file_are_parsed():
    # Regression: 15 of 49 real papers (e.g. 2609.23585) keep \bibitem entries
    # in the .tex file itself, with no .bib or .bbl file.
    tex = TEX.replace(r"\end{document}", BBL + "\n" + r"\end{document}").replace("smith2020", "vaswani2017")
    pairs, refs = latex.citation_pairs({"main.tex": tex})
    assert refs["vaswani2017"]["title"] == "Attention is all you need"
    assert [p["key"] for p in pairs] == ["vaswani2017"]


def test_read_archive_tar_and_single_gzip(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in {"paper.tex": TEX, "refs.bib": BIB, "fig.png": "x"}.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    tar_path = tmp_path / "a"
    tar_path.write_bytes(buf.getvalue())
    assert set(latex.read_archive(tar_path)) == {"paper.tex", "refs.bib"}

    gz_path = tmp_path / "b"
    gz_path.write_bytes(gzip.compress(TEX.encode()))
    assert set(latex.read_archive(gz_path)) == {"main.tex"}

    pdf_path = tmp_path / "c"
    pdf_path.write_bytes(b"%PDF-1.5 not a tex source")
    assert latex.read_archive(pdf_path) == {}


def test_math_symbol_commands_become_symbols_not_deleted():
    # Regression: real paper 2609.23376 had "$2 \times 10^{-4}$" extracted as "$2 10^-4$".
    tex = (r"\begin{document}We use a learning rate of $2 \times 10^{-4}$ and $\lambda \leq 0.5$ "
           r"as in prior work \cite{lee2021}.\end{document}")
    pairs, _ = latex.citation_pairs({"main.tex": tex, "refs.bib": BIB})
    assert "2 × 10^-4" in pairs[0]["claim"] and "≤ 0.5" in pairs[0]["claim"]


def test_var_greek_letters_are_converted_too():
    # Regression: 2609.* rendered "$(\delta, \varepsilon)$" as "$(δ, )$".
    tex = r"\begin{document}An algorithm finds a $(\delta, \varepsilon)$-stationary point quickly \cite{lee2021}.\end{document}"
    pairs, _ = latex.citation_pairs({"main.tex": tex, "refs.bib": BIB})
    assert "(δ, ε)" in pairs[0]["claim"]
