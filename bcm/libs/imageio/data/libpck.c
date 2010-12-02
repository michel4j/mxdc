/***********************************************************************
 * 
 * pck1
 *
 * Copyright by:	Dr. Claudio Klein
 * 			X-ray Research GmbH, Hamburg
 * Pck format by:	Dr. J.P. Abrahams
 *			LMB, MRC Cambridge, UK
 *
 * Version: 	1.0 
 * Date:	12/02/1997
 *
 **********************************************************************/
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <math.h>
#include <ctype.h>
#include <string.h>

#define BYTE char
#define WORD short int
#define LONG int

#define MAX_NON_OVERFLOW 65535
#define FPOS(a)          ((int)( a/8. + 0.875 )*64)

#define PACKIDENTIFIER "\nCCP4 packed image, X: %04d, Y: %04d\n"
#define PACKBUFSIZ BUFSIZ
#define DIFFBUFSIZ 16384L
#define max(x, y) (((x) > (y)) ? (x) : (y)) 
#define min(x, y) (((x) < (y)) ? (x) : (y)) 
#define abs(x) (((x) < 0) ? (-(x)) : (x))
const LONG setbits[33] = {0x00000000L, 0x00000001L, 0x00000003L, 0x00000007L,
			  0x0000000FL, 0x0000001FL, 0x0000003FL, 0x0000007FL,
			  0x000000FFL, 0x000001FFL, 0x000003FFL, 0x000007FFL,
			  0x00000FFFL, 0x00001FFFL, 0x00003FFFL, 0x00007FFFL,
			  0x0000FFFFL, 0x0001FFFFL, 0x0003FFFFL, 0x0007FFFFL,
			  0x000FFFFFL, 0x001FFFFFL, 0x003FFFFFL, 0x007FFFFFL,
			  0x00FFFFFFL, 0x01FFFFFFL, 0x03FFFFFFL, 0x07FFFFFFL,
			  0x0FFFFFFFL, 0x1FFFFFFFL, 0x3FFFFFFFL, 0x7FFFFFFFL,
                          0xFFFFFFFFL};
#define shift_left(x, n)  (((x) & setbits[32 - (n)]) << (n))
#define shift_right(x, n) (((x) >> (n)) & setbits[32 - (n)])

/******************************************************************************/
/*
 * Function prototypes
 */
static void 	get_pck		(FILE *,           WORD *);
static void 	unpack_wordmar	(FILE *, int, int, WORD *);
static void 	rotate_clock90	(WORD *, int);
static void 	swaplong	();
int		openfile	(char *, WORD *);

/***************************************************************************
 * Function: open_file
 ***************************************************************************/
int
openfile(char *c_file, WORD *img) 
{
unsigned short	i16, *i2;
int		i32,n,j,row,col,i=0;
int		head[10], nx, n32,total, ihigh,high[2];
short		is;
FILE    	*fp;
	

	/* Open file */

	if ( (fp = fopen( c_file, "r" ) ) == NULL ) {
		printf("ERROR> Cannot open file %s\n",c_file);
		return;
	}

	/* Read header */
	if (fread(head,sizeof(int), 10, fp) != 10 ) {
		printf("ERROR> Cannot read header of %s\n",c_file);
		return;
	}

	/* Get packed 16 bit array with nx*nx elements */
	get_pck( fp, img );
	

	/* Close file and return */
CLOSE:
	fclose( fp );
	return 0;
}

/***************************************************************************
 * Function: get_pck
 ***************************************************************************/
static void 
get_pck(FILE *fp, WORD *img)
{ 
int 	x = 0, y = 0, i = 0, c = 0;
char 	header[BUFSIZ];

  	if (fp == NULL) return;

	rewind( fp );
	header[0] = '\n';
	header[1] = 0;

	/*
	 * Scan file until PCK header is found
	 */
	while ((c != EOF) && ((x == 0) || (y == 0))) {
		c = i = x = y = 0;
		while ((++i < BUFSIZ) && (c != EOF) && (c != '\n') && (x==0) && (y==0))
			if ((header[i] = c = getc(fp)) == '\n')
				sscanf(header, PACKIDENTIFIER, &x, &y);
	}

	unpack_wordmar(fp, x, y, img);
}


/*****************************************************************************
 * Function: unpack_word
 * Unpacks a packed image into the WORD-array 'img'. 
 *****************************************************************************/
static void 
unpack_wordmar(FILE *packfile, int x, int y, WORD *img)
{ 
int 		valids = 0, spillbits = 0, usedbits, total = x * y;
LONG 		window = 0L, spill, pixel = 0, nextint, bitnum, pixnum;
static int 	bitdecode[8] = {0, 4, 5, 6, 7, 8, 16, 32};

	while (pixel < total) {
	    if (valids < 6) {
    		if (spillbits > 0) {
      			window |= shift_left(spill, valids);
        		valids += spillbits;
        		spillbits = 0;
		    } else {
      			spill = (LONG) getc(packfile);
        		spillbits = 8;
		    }
	    } else {
    		pixnum = 1 << (window & setbits[3]);
      		window = shift_right(window, 3);
      		bitnum = bitdecode[window & setbits[3]];
      		window = shift_right(window, 3);
      		valids -= 6;
      		while ((pixnum > 0) && (pixel < total)) {
      		    if (valids < bitnum) {
        		    if (spillbits > 0) {
          		        window |= shift_left(spill, valids);
            		    if ((32 - valids) > spillbits) {
            			    valids += spillbits;
              			    spillbits = 0;
			            } else {
            			    usedbits = 32 - valids;
			                spill = shift_right(spill, usedbits);
			                spillbits -= usedbits;
			                valids = 32;
			            }
			        } else {
          		        spill = (LONG) getc(packfile);
            		    spillbits = 8;
			        }
		        } else {
        		    --pixnum;
		  	        if (bitnum == 0)
            		    nextint = 0;
          		    else {
          		        nextint = window & setbits[bitnum];
            		    valids -= bitnum;
            		    window = shift_right(window, bitnum);
		                if ((nextint & (1 << (bitnum - 1))) != 0)
		              	    nextint |= ~setbits[bitnum];
			        }
          		    if (pixel > x) {
         		        img[pixel] = (WORD) (nextint +
                                      (img[pixel-1] + img[pixel-x+1] +
                                       img[pixel-x] + img[pixel-x-1] + 2) / 4);
            		    ++pixel;
			        } else if (pixel != 0) {
          		        img[pixel] = (WORD) (img[pixel - 1] + nextint);
            		    ++pixel;
			        } else img[pixel++] = (WORD) nextint;
		        }
		    }
	    }
	}
}

/*****************************************************************************
 * Function: rotate_clock90 = rotates image by +90 deg.
 *****************************************************************************/
static void
rotate_clock90(WORD *data, int nx)
{
register WORD   *ptr1, *ptr2, *ptr3, *ptr4, temp;
register int    i, j;
int             nx2 = (nx+1)/2;

        for ( i=nx/2; i--; ) {
                /* Set pointer addresses */

                j    = nx2 - 1;
                ptr1 = data + nx*i        + j;          /* 1. Quadrant */
                ptr2 = data + nx*j        + nx-1-i;     /* 2. Quadrant */
                ptr3 = data + nx*(nx-1-i) + nx-1-j;     /* 4. Quadrant */
                ptr4 = data + nx*(nx-1-j) + i;          /* 3. Quadrant */

                for ( j = nx2; j--; ) {

                        /* Restack: clockwise rotation by 90.0 */
                        temp  = *ptr4;
                        *ptr4 = *ptr3;
                        *ptr3 = *ptr2;
                        *ptr2 = *ptr1;
                        *ptr1 = temp;

                        /* Increase pointer */
                         ptr1 --;
                         ptr2 -= nx;
                         ptr3 ++;
                         ptr4 += nx;
                }
        }
}

/*****************************************************************************
 * Function: swaplong = swaps bytes of 32 bit values
 *****************************************************************************/
static void
swaplong(char *data, int nbytes)
{
register int i, t1, t2, t3, t4;

        for(i=nbytes/4;i--;) {
                t1 = data[i*4+3];
                t2 = data[i*4+2];
                t3 = data[i*4+1];
                t4 = data[i*4+0];
                data[i*4+0] = t1;
                data[i*4+1] = t2;
                data[i*4+2] = t3;
                data[i*4+3] = t4;
        }
}

