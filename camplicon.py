import argparse
from Bio import Seq,SeqIO
import glob
import gc
import itertools
import multiprocessing as mp
import numpy as np
import re
import subprocess
import sys
import shutil

class Kmer:
    # Class to store a kmer. ID is based on position in the input file, frequency from the input file and melting temperature is calculated by Primer3
    __slots__ = ['id', 'seq', 'freq', 'melt']
    
    def __init__(self, id, seq, freq, melt=-1):
        self.id = str(id)
        self.seq = str(seq)
        self.freq = int(freq)
        self.melt = float(melt)

    def __repr__(self):
        return("{}: {} occurred {} times; Tm={}C".format(self.id,self.seq,self.freq,self.melt))

    def __str__(self):
        return("{}\t{}\t{}".format(self.id,self.seq,self.melt))

class Kmer_hit:
    # Class to store a kmer hit on a target genome, parsed from the results of BWA aln > samse
    __slots__ = ['kmer_id', 'target', 'strand', 'pos', 'edist']

    def __init__(self, kmer_id, target, strand, pos, edist):
        self.kmer_id = str(kmer_id)
        self.target = str(target)
        self.strand = int(strand)
        self.pos = int(pos)
        self.edist = int(edist)

    def __repr__(self):
        return("Kmer {} aligns to {}:{}:{} with edit distance {}".format(self.kmer_id,self.target,self.strand,self.pos,self.edist))

class Kmer_pair:
    # Class to store a kmer pair. Penalty calculated by Primer3, and other statistics calculated based on target products
    __slots__ = ['pair_id', 'left', 'right', 'penalty', 'nhits', 'length', 'se', 'nseq', 'info','offhits','offseqs','overlap']

    def __init__(self, pair_id, kmer1, kmer2, penalty=-1, nhits=0, length=0, se=0, nseq=0, info=0, offhits=0, offseqs=0, overlap=0):
        self.pair_id = str(pair_id)
        self.left = kmer1
        self.right = kmer2
        self.penalty = float(penalty)
        self.nhits = int(nhits)
        self.length = float(length)
        self.se = float(se)
        self.nseq = int(nseq)
        self.info = float(info)
        self.offhits = int(offhits)
        self.offseqs = int(offseqs)
        self.overlap = int(overlap)

    def __repr__(self):
        return("Pair {} with kmers {}<=>{}; penalty={}; hits {} targets with mean length={}; stderr={}; {} sequences with {} bits; {} off-target hits, {} sequences of which {} overlap".format(self.pair_id,self.left.id,self.right.id,self.penalty,self.nhits,self.length,self.se,self.nseq,self.info,self.offhits,self.offseqs,self.overlap))

    def __str__(self):
        return("{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}".format(self.left,self.right,self.nhits,self.nseq,self.info,self.penalty,self.length,self.se,self.offhits,self.offseqs,self.overlap))

def run_kmc(genomes,kmc_dir,threads,kmer_len,bg=None):
    # Run kmc on the first file
    output = subprocess.check_output("{}/kmc -t{} -k{} -ci1 -cx1 -cs8192 -fm {} db /tmp/".format(kmc_dir,threads,kmer_len,genomes[0]),shell=True).decode()
    lines = output.split("\n")

    if bg is not None:
        output = subprocess.check_output("{}/kmc -t{} -k{} -ci1 -cx1 -cs8192 -fm {} current /tmp/".format(kmc_dir,threads,kmer_len,bg),shell=True).decode()
        output = subprocess.check_output("{}/kmc_tools -t{} simple db current -cx9999 kmers_subtract new -cs8192".format(kmc_dir,threads),shell=True).decode()
        shutil.move("new.kmc_pre","db.kmc_pre")
        shutil.move("new.kmc_suf","db.kmc_suf")
        sys.stderr.write("{}\n".format(bg))
    else:
        for genome in genomes[1:]:
            output = subprocess.check_output("{}/kmc -t{} -k{} -ci1 -cx1 -cs8192 -fm {} current /tmp/".format(kmc_dir,threads,kmer_len,genome),shell=True).decode()
            output = subprocess.check_output("{}/kmc_tools -t{} simple current db -cx9999 union new -cs8192".format(kmc_dir,threads),shell=True).decode()
            shutil.move("new.kmc_pre","db.kmc_pre")
            shutil.move("new.kmc_suf","db.kmc_suf")
            sys.stderr.write("{}\n".format(genome))

    output = subprocess.check_output("{}/kmc_dump db ukmc.txt".format(kmc_dir),shell=True).decode()

    # Read in the results and format them
    kmer_counts = dict()
    with open("ukmc.txt",'r') as fi:
        for line in fi:
            key,value = line.strip().split("\t")
            kmer_counts[key] = int(value)
    
    return(kmer_counts)

def read_kmc(kmc_file):
    # Import kmer frequency statistics from the output of kmc
    kmers = []
    with open(kmc_file,'r') as fi:
        for i,line in enumerate(fi):
            fields = line.strip().split("\t")
            kmer = Kmer(i,fields[0],fields[1])
            kmers.append(kmer)
    return(kmers)

def rc_kmer(kmer):
    # Reverse complement a kmer (as kmc produces statistics for kmers on 1 strand counted across both)
    new_id = "{}rc".format(kmer.id)
    new_seq = str(Seq.Seq(kmer.seq).reverse_complement())
    new_kmer = Kmer(new_id,new_seq,kmer.freq,kmer.melt)
    return(new_kmer)

def check_kmer_primer3(kmer,p3_config):
    # Check kmer for reasonableness as a primer with Pirimer3
    argument = "SEQUENCE_ID=primer_pair\\nPRIMER_TASK=check_primers\\nSEQUENCE_PRIMER={}\\nPRIMER_THERMODYNAMIC_PARAMETERS_PATH={}\\n=".format(kmer.seq,p3_config)
    output = subprocess.check_output("primer3_core <(printf \"{}\")".format(argument),shell=True,executable="/bin/bash").decode()
    if not re.findall('PRIMER_LEFT_NUM_RETURNED=0',output):
        lines = output.split("\n")[1:-2]
        param = {}
        for line in lines:
            parts = line.split("=")
            param[parts[0]] = parts[1]
        kmer.melt = float(param['PRIMER_LEFT_0_TM'])
    return(kmer)

def kmers_fasta(kmers,filename):
    # Output kmers to a fasta file for alignment
    with open(filename,'w') as fo:
        for kmer in kmers:
            fo.write(">{}\n{}\n".format(kmer.id,kmer.seq))

def align_kmers(kmers_file,target_file):
    # Align kmers fasta file against a target file with BWA, allowing only 1 error
    sys.stderr.write("Aligning {}\n".format(target_file))
    subprocess.run("bwa index {} 2> /dev/null".format(target_file),shell=True,executable="/bin/bash")
    aln = subprocess.check_output("bwa aln -n 1 {} {} 2> /dev/null | bwa samse {} - {} 2> /dev/null".format(target_file,kmers_file,target_file,kmers_file),shell=True,executable="/bin/bash").decode()
    aln = aln.strip().split("\n")
    return(aln)

def parse_aln(aln):
    # Parse a BWA alignment and return hits in useful format
    kmer_hits = {}
    for line in aln:
        if line[0] != '@':
            fields = line.strip().split("\t")
            if fields[1] != '4':
                strand = (int(fields[1])/8)-1
                edist = re.sub("NM:i:","",fields[12])
                kmer_hit = Kmer_hit(fields[0], fields[2], strand, fields[3], edist)
                kmer_hits[kmer_hit.kmer_id] = kmer_hit
    return(kmer_hits)

def make_kmer_pairs(kmers):
    # Create all possible pairs of primers
    kmer_pairs = []
    for i,(x,y) in enumerate(itertools.combinations(kmers,2)):
        kmer_pairs.append(Kmer_pair(i,x,y))
    return(kmer_pairs)

def check_kmer_pair_primer3(kmer_pair,p3_config):
    # Primer3 doesn't function for a sequence and its exact reverse complement
    if str(Seq.Seq(kmer_pair.left.seq).reverse_complement()) == kmer_pair.right.seq:
        return(kmer_pair)

    argument = "SEQUENCE_ID=primer_pair\\nPRIMER_TASK=check_primers\\nSEQUENCE_PRIMER={}\\nSEQUENCE_PRIMER_REVCOMP={}\\nPRIMER_THERMODYNAMIC_PARAMETERS_PATH={}\\n=".format(
                kmer_pair.left.seq,kmer_pair.right.seq,p3_config)
    output = subprocess.check_output("primer3_core <(printf \"{}\")".format(argument),shell=True,executable="/bin/bash").decode()
    if not re.findall('PRIMER_PAIR_NUM_RETURNED=0',output):
        lines = output.split("\n")[1:-2]
        param = {}
        for line in lines:
            parts = line.split("=")
            param[parts[0]] = parts[1]
        kmer_pair.penalty = float(param['PRIMER_PAIR_0_PENALTY'])
    return(kmer_pair)

def read_genome(genome_file):
    genome = SeqIO.to_dict(SeqIO.parse(genome_file,'fasta'))
    return(genome)
        
def generate_product(kmer_pair,kmer_hits,genome):
    # Check if kmers hit anything
    if kmer_pair.left.id in kmer_hits.keys():
        lhit = kmer_hits[kmer_pair.left.id]
    else:
        return(None)
    if kmer_pair.right.id in kmer_hits.keys():
        rhit = kmer_hits[kmer_pair.right.id]
    else:
        return(None)

    # Check if kmers are on opposite strands
    if lhit.strand == rhit.strand:
        return(None)

    # Check if kmers are on the same contig
    if lhit.target==rhit.target:
        if lhit.pos < rhit.pos:
            product = str(genome[lhit.target].seq[(lhit.pos-1):(rhit.pos+19)])
        else:
            product = str(genome[rhit.target].seq[(rhit.pos-1):(lhit.pos+19)])
        # Remove huge products, likely the result of hits at both ends of the linear genome sequence
        if len(product) > 10000:
           product = None
    else:
        product = None

    return(product)

def generate_products_from_genome(kmers,kmers_file,genome_file,kmer_pairs):
    genome = read_genome(genome_file)
    aln = align_kmers(kmers_file,genome_file)
    kmer_hits = parse_aln(aln)

    products = {kmer_pair.pair_id:generate_product(kmer_pair,kmer_hits,genome) for kmer_pair in kmer_pairs}
    return(products)

def list_entropy(l):
    freq = [l.count(x)/len(l) for x in set(l)]
    entropy = [-x*np.log2(x) for x in freq]
    return(np.sum(entropy))

def score_kmer_pair(kmer_pair,products,bg_products,min_length,max_length):
    good_products = [product for product in products if (product is not None) and (max_length > len(product) > min_length)]
    kmer_pair.nhits = len(good_products)
    kmer_pair.nseq = len(set(good_products))
    if kmer_pair.nhits > 0:
        kmer_pair.length = np.mean([len(product) for product in good_products])
        kmer_pair.se = np.std([len(product) for product in good_products])/np.sqrt(len(good_products))
        kmer_pair.info = list_entropy(good_products)

    good_bg_products = [product for product in bg_products if (product is not None) and (max_length > len(product) > min_length)]
    kmer_pair.offhits = len(good_bg_products)
    kmer_pair.offseqs = len(set(good_bg_products))
    kmer_pair.overlap = len([bg_product for bg_product in set(good_bg_products) if bg_product in good_products])

    return(kmer_pair)

#def __main__():
if True:
    parser = argparse.ArgumentParser(description='Find kmers that will act as effective custom amplicon primers')
    parser.add_argument('genomes',metavar='genomes_dir',help='Directory containing genomes in fasta format')
    parser.add_argument('background',metavar='background_dir',help='Directory containing background genomes in fasta format')
    parser.add_argument('--bg',help='Background genome, when only one genome is the target')
    parser.add_argument('--kmc_dir',help='Directory containing the KMC executables')
    parser.add_argument('--kmc_counts',help='Sorted count file produced by KMC')
    parser.add_argument('--kmer_len',default=20,type=int,help='Kmer/primer length')
    parser.add_argument('--min',metavar='min_length',default=300,type=int,help='Minimum PCR product length')
    parser.add_argument('--max',metavar='max_length',default=500,type=int,help='Maximum PCR product length')
    parser.add_argument('--p3',metavar='p3_config',default='/nfs/modules/modules/software/Primer3/2.4.0-foss-2018b/primer3-2.4.0/src/primer3_config/',help='Path to Primer3 config directory')
    parser.add_argument('--threads',metavar='threads',default=8,type=int,help='Number of threads for execution')

    args = parser.parse_args()

    if (args.kmc_dir is None) and (args.kmc_counts is None):
        exit("One of --kmc_dir or --kmc_counts must be provided. Exiting..")

    pool = mp.Pool(args.threads)

    # Read in kmers, filter with Primer3 and generate reverse complements
    genome_files = glob.glob('{}/*.fasta'.format(args.genomes))
    if len(genome_files) == 1:
        if args.bg is None:
            exit("For only one genome, an example background genome must be provided, as closely related as possible")
    if args.kmc_counts is not None:
        kmers = read_kmc(args.kmc_counts)
    else:
        if len(genome_files) == 1:
            kmers = run_kmc(genome_files,args.kmc_dir,args.threads,args.kmer_len,args.bg)
        else:
            kmers = run_kmc(genome_files,args.kmc_dir,args.threads,args.kmer_len)
        max_freq = max(kmers.values())
        kmers = {k:v for k,v in kmers.items() if v==max_freq}
        kmers = [Kmer(i,k,v) for i,(k,v) in enumerate(kmers.items())]
    kmers = pool.starmap(check_kmer_primer3,[(kmer,args.p3) for kmer in kmers])
    kmers = [kmer for kmer in kmers if kmer.melt > -1]
    kmers.extend([rc_kmer(x) for x in kmers])
    kmers_fasta(kmers,"kmers.fasta")

    # Generate kmer pairs
    kmer_pairs = make_kmer_pairs(kmers)
    kmer_pairs = pool.starmap(check_kmer_pair_primer3,[(kmer_pair,args.p3) for kmer_pair in kmer_pairs])

    # Generate products for each kmer pair for each genome
    all_products = pool.starmap(generate_products_from_genome,[(kmers,"kmers.fasta",genome_file,kmer_pairs) for genome_file in genome_files])

    # Rearrange all products to first reference kmer pair, then genome
    all_products = {kmer_pair:[products[kmer_pair.pair_id] for products in all_products] for kmer_pair in kmer_pairs}

    # Generate products for each kmer pair for each off-target genome
    bg_files = glob.glob('{}/*.fasta'.format(args.background))
    bg_products = pool.starmap(generate_products_from_genome,[(kmers,"kmers.fasta",bg_file,kmer_pairs) for bg_file in bg_files])

    # Rearrange bg products to first reference kmer pair, then genome
    bg_products = {kmer_pair:[products[kmer_pair.pair_id] for products in bg_products] for kmer_pair in kmer_pairs}

    # Score kmer pairs
    kmer_pairs = [score_kmer_pair(kmer_pair,all_products[kmer_pair],bg_products[kmer_pair],args.min,args.max) for kmer_pair in kmer_pairs]

    # Filter and sort kmer pairs
    kmer_pairs = [kmer_pair for kmer_pair in kmer_pairs if kmer_pair.nhits > 0]
    kmer_pairs = sorted(kmer_pairs, key=lambda kmer_pair: (kmer_pair.nhits, kmer_pair.nseq, kmer_pair.info, -kmer_pair.penalty), reverse=True)

    # Output results
    sys.stdout.write("kmer1_id\tkmer1_seq\tkmer1_temp\tkmer2_id\tkmer2_seq\tkmer2_temp\tn_targets\tn_seqs\tinfo\tpenalty\tmean_len\tstd_len\toff_targets\toff_seqs\toverlap\n")
    for kmer_pair in kmer_pairs:
        sys.stdout.write("{}\n".format(kmer_pair))

    pool.close()

#if __name__ == "__main__":
#    __main__()

