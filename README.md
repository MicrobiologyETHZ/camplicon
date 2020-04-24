# camplicon

IN DEVELOPMENT

Find kmers that will act as effective custom amplicon primers

positional arguments:
  genomes_dir           Directory containing genomes in fasta format
  background_dir        Directory containing background genomes in fasta
                        format

optional arguments:
  -h, --help            show this help message and exit
  --bg BG               Background genome, when only one genome is the target
  --kmc_dir KMC_DIR     Directory containing the KMC executables
  --kmc_counts KMC_COUNTS
                        Sorted count file produced by KMC
  --kmer_len KMER_LEN   Kmer/primer length
  --min min_length      Minimum PCR product length
  --max max_length      Maximum PCR product length
  --p3 p3_config        Path to Primer3 config directory
  --threads threads     Number of threads for execution

KMC is available from https://github.com/refresh-bio/KMC

## How it works
KMC is used to find the unique kmers in a genome, which are then added to a master count of kmers and the number of genomes they appear in uniquely. For now we ignore that some kmers may appear multiple times in a specific genome and therefore be unsuitable as unique primers.

From there, each kmer is checked for viability as a PCR primer with Primer3. All possible pairs are constructed from viable primers and are then checked again by Primer3.

Next, *in silico* PCR is performed to find the possible products for the in-group of genomes for each primer pair, discarding any that are too long or short.

Finally, BWA is used to align the primers to the out-group genomes, and another round of *in silico* PCR determines the possible products that might be created.

The output summarises the primer pairs' melting temperatures, number of in-group genomes hit, number of different sequence products produced, information content of products, penalty assigned by Primer3, the mean and stdev in the length of products, the number of out-group genomes hit, the number of different out-group sequence products produced and the overlap between the in-group and out-group products.
