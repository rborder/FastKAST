# Fast Kernel-based Association Testing of non-linear genetic effectsfor Biobank-scale data

FastKAST is a highly scalable method for testing complex nonlinear relationships between a set of SNPs with a target trait. FastKAST uses a kernel function to model these non-linear relationships. Since direct computation using the kernel function is computationally prohibitive, FastKast uses insights from modern scalable machine learning to obtain an approximation that is efficient to compute. In particular, FastKAST is scalable to large sample size, and testing on 500K set with 30 snps can be done with a few minutes


## Exmaple
```
python testing.py --bfile all --phen all.pheno
```
